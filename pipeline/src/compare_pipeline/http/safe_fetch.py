import ipaddress
import socket
import time
import urllib.parse

import httpx

# Blocked IP networks
PROHIBITED_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
ALLOWED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/json",
}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_REDIRECTS = 5

_domain_last_request: dict[str, float] = {}


class SSRFSecurityError(Exception):
    """Raised when a URL attempts to target private, local, or prohibited network resources."""


class SafeFetchError(Exception):
    """Raised when fetch fails due to size, timeout, or disallowed content type."""


def is_ip_prohibited(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Checks if an IP address belongs to private, loopback, link-local, multicast or metadata spaces."""
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
    ):
        return True
    if ip in PROHIBITED_METADATA_IPS:
        return True
    return False


def validate_target_url(url: str) -> urllib.parse.ParseResult:
    """Validates URL scheme, port, and performs DNS resolution checks to prevent SSRF."""
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRFSecurityError(
            f"Disallowed URL scheme: '{parsed.scheme}'. Only http and https are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("URL missing valid hostname.")

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise SSRFSecurityError(
            f"Disallowed port: {port}. Only ports 80 and 443 are allowed."
        )

    # DNS Resolution check
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SafeFetchError(
            f"DNS resolution failed for hostname '{hostname}': {e}"
        ) from e

    resolved_ips: set[str] = set()
    for item in addr_info:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        resolved_ips.add(ip_str)
        ip_obj = ipaddress.ip_address(ip_str)
        if is_ip_prohibited(ip_obj):
            raise SSRFSecurityError(
                f"Prohibited IP target: hostname '{hostname}' resolves to private/loopback/metadata address {ip_str}"
            )

    return parsed


def enforce_domain_rate_limit(domain: str, min_delay_sec: float = 1.0) -> None:
    """Enforces polite crawling: at least 1 second between requests per domain."""
    now = time.time()
    last_req = _domain_last_request.get(domain, 0.0)
    elapsed = now - last_req
    if elapsed < min_delay_sec:
        time.sleep(min_delay_sec - elapsed)
    _domain_last_request[domain] = time.time()


def safe_fetch(
    url: str,
    timeout_sec: float = 15.0,
    headers: dict[str, str] | None = None,
    verify_ssl: bool = True,
    apply_rate_limit: bool = True,
) -> httpx.Response:
    """
    Safely fetches a web resource with comprehensive SSRF validation,
    redirect security checks, 5 MB payload limit, and content-type verification.
    """
    current_url = url
    redirect_count = 0

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 (OtamiserResearchBot/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        req_headers.update(headers)

    while True:
        parsed = validate_target_url(current_url)
        domain = parsed.hostname or ""

        if apply_rate_limit:
            enforce_domain_rate_limit(domain)

        with httpx.Client(
            follow_redirects=False,
            timeout=timeout_sec,
            verify=verify_ssl,
        ) as client:
            try:
                # Stream to enforce 5 MB limit
                with client.stream("GET", current_url, headers=req_headers) as response:
                    # Check redirect
                    if response.is_redirect:
                        redirect_count += 1
                        if redirect_count > MAX_REDIRECTS:
                            raise SafeFetchError(
                                f"Exceeded maximum redirects ({MAX_REDIRECTS})"
                            )
                        loc = response.headers.get("Location")
                        if not loc:
                            raise SafeFetchError("Redirect missing Location header")
                        current_url = urllib.parse.urljoin(current_url, loc)
                        continue

                    # Validate HTTP status
                    response.raise_for_status()

                    # Validate content-type
                    content_type = (
                        response.headers.get("Content-Type", "")
                        .split(";")[0]
                        .strip()
                        .lower()
                    )
                    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                        raise SafeFetchError(
                            f"Disallowed content-type: '{content_type}'"
                        )

                    # Read body with 5 MB cap
                    body_bytes = bytearray()
                    for chunk in response.iter_bytes():
                        body_bytes.extend(chunk)
                        if len(body_bytes) > MAX_RESPONSE_BYTES:
                            raise SafeFetchError(
                                f"Response size exceeded {MAX_RESPONSE_BYTES} bytes limit"
                            )

                    # Copy headers and remove content-encoding since body_bytes is already decoded
                    cleaned_headers = dict(response.headers)
                    cleaned_headers.pop("content-encoding", None)
                    cleaned_headers.pop("content-length", None)

                    # Construct standalone synthetic response to return
                    built_response = httpx.Response(
                        status_code=response.status_code,
                        headers=cleaned_headers,
                        content=bytes(body_bytes),
                        request=response.request,
                    )
                    return built_response

            except httpx.HTTPError as e:
                raise SafeFetchError(
                    f"HTTP request failed for {current_url}: {e}"
                ) from e
