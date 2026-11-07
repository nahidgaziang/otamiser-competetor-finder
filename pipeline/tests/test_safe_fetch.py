import pytest
import respx

from compare_pipeline.http.safe_fetch import (
    SafeFetchError,
    SSRFSecurityError,
    safe_fetch,
    validate_target_url,
)


def test_ssrf_prohibited_ips():
    """Validates that SSRF protection blocks loopback, private, and metadata targets."""
    prohibited_urls = [
        "http://127.0.0.1:80",
        "http://localhost:80",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1:80",
        "http://192.168.1.1:80",
        "http://172.17.0.1:80",
        "http://[::1]:80",
    ]

    for url in prohibited_urls:
        with pytest.raises(SSRFSecurityError) as exc_info:
            validate_target_url(url)
        assert (
            "prohibited" in str(exc_info.value).lower()
            or "scheme" in str(exc_info.value).lower()
        )


def test_disallowed_schemes_and_ports():
    """Validates scheme allowlist (http/https only) and port allowlist (80/443 only)."""
    with pytest.raises(SSRFSecurityError):
        validate_target_url("ftp://example.com")

    with pytest.raises(SSRFSecurityError):
        validate_target_url("file:///etc/passwd")

    with pytest.raises(SSRFSecurityError):
        validate_target_url("http://example.com:22")

    with pytest.raises(SSRFSecurityError):
        validate_target_url("http://example.com:5432")


@respx.mock
def test_safe_fetch_content_type_enforcement():
    """Validates that disallowed content-types (e.g. binaries, executables) are rejected."""
    # Mock public domain resolving safely
    respx.get("https://example.com/test.exe").respond(
        status_code=200,
        headers={"Content-Type": "application/octet-stream"},
        content=b"binary content",
    )

    with pytest.raises(SafeFetchError) as exc_info:
        safe_fetch("https://example.com/test.exe", apply_rate_limit=False)

    assert "disallowed content-type" in str(exc_info.value).lower()


@respx.mock
def test_safe_fetch_size_cap():
    """Validates that response payloads exceeding 5 MB are aborted."""
    large_payload = b"A" * (5 * 1024 * 1024 + 1024)  # > 5 MB
    respx.get("https://example.com/large.html").respond(
        status_code=200,
        headers={"Content-Type": "text/html"},
        content=large_payload,
    )

    with pytest.raises(SafeFetchError) as exc_info:
        safe_fetch("https://example.com/large.html", apply_rate_limit=False)

    assert "exceeded" in str(exc_info.value).lower()


@respx.mock
def test_safe_fetch_redirect_to_internal_ip_blocked():
    """Validates that a redirect from a public host to an internal loopback IP is caught and blocked."""
    respx.get("https://example.com/redirect").respond(
        status_code=302,
        headers={"Location": "http://127.0.0.1:80/admin"},
    )

    with pytest.raises(SSRFSecurityError):
        safe_fetch("https://example.com/redirect", apply_rate_limit=False)
