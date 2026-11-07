"""safe_fetch / crawl: SSRF protection, polite crawling, response limits (guide sections 6.5 and 8)."""

from __future__ import annotations

import ipaddress
import socket

import httpx
import pytest
import respx

import importlib

from compare_pipeline import crawl
from compare_pipeline.http.safe_fetch import (
    SafeFetchError,
    SSRFSecurityError,
    is_ip_prohibited,
    safe_fetch,
    validate_target_url,
)

# compare_pipeline.http re-exports the safe_fetch *function* under the module's name, so fetch the
# module object explicitly.
sf = importlib.import_module("compare_pipeline.http.safe_fetch")

PUBLIC_IP = "93.184.215.14"


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every hostname resolve to a public IP so tests never depend on real DNS."""

    def fake_getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port or 443))]

    monkeypatch.setattr(sf.socket, "getaddrinfo", fake_getaddrinfo)
    sf._domain_last_request.clear()


# --- address classification -------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.17.0.1",  # default Docker bridge
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "0.0.0.0",  # noqa: S104
        "::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:169.254.169.254",
        "fe80::1",
        "fc00::1",
        "fd00:ec2::254",
        "100.64.0.1",
    ],
)
def test_internal_addresses_are_prohibited(ip: str) -> None:
    assert is_ip_prohibited(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip: str) -> None:
    assert is_ip_prohibited(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://example.com:70/",
        "http://example.com:22/",
        "http://example.com:5432/",
        "http://[::1]/",
        "http://localhost./",
    ],
)
def test_bad_schemes_ports_and_hosts_rejected(url: str) -> None:
    with pytest.raises(SSRFSecurityError):
        validate_target_url(url)


def test_url_without_host_rejected() -> None:
    with pytest.raises(SSRFSecurityError):
        validate_target_url("http:///nohost")


# --- fetch behaviour -----------------------------------------------------------------------------


@respx.mock
def test_redirect_chain_longer_than_five_is_refused(public_dns: None) -> None:
    for i in range(7):
        respx.get(f"https://example.com/r{i}").respond(
            302, headers={"Location": f"https://example.com/r{i + 1}"}
        )
    with pytest.raises(SafeFetchError, match="redirects"):
        safe_fetch("https://example.com/r0", apply_rate_limit=False)


@respx.mock
def test_redirect_to_metadata_service_is_blocked(
    public_dns: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = sf.socket.getaddrinfo

    def resolver(host, port, *a, **k):  # noqa: ANN001
        if host == "169.254.169.254":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]
        return real(host, port, *a, **k)

    monkeypatch.setattr(sf.socket, "getaddrinfo", resolver)
    respx.get("https://example.com/go").respond(
        302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
    )
    with pytest.raises(SSRFSecurityError):
        safe_fetch("https://example.com/go", apply_rate_limit=False)


@respx.mock
def test_successful_fetch_returns_body(public_dns: None) -> None:
    respx.get("https://example.com/ok").respond(
        200, headers={"Content-Type": "text/html; charset=utf-8"}, text="<p>hi</p>"
    )
    resp = safe_fetch("https://example.com/ok", apply_rate_limit=False)
    assert resp.status_code == 200
    assert "hi" in resp.text


@respx.mock
def test_http_error_status_raises_safe_fetch_error(public_dns: None) -> None:
    respx.get("https://example.com/missing").respond(404)
    with pytest.raises(SafeFetchError):
        safe_fetch("https://example.com/missing", apply_rate_limit=False)


@respx.mock
def test_missing_content_type_is_rejected(public_dns: None) -> None:
    respx.get("https://example.com/blob").respond(200, content=b"\x00\x01binary")
    with pytest.raises(SafeFetchError):
        safe_fetch("https://example.com/blob", apply_rate_limit=False)


@respx.mock
def test_user_agent_identifies_the_crawler_honestly(public_dns: None) -> None:
    route = respx.get("https://example.com/ua").respond(
        200, headers={"Content-Type": "text/html"}, text="ok"
    )
    safe_fetch("https://example.com/ua", apply_rate_limit=False)
    ua = route.calls.last.request.headers["User-Agent"]
    assert "Mozilla" not in ua and "Chrome" not in ua
    assert "bot" in ua.lower()


@respx.mock
def test_robots_txt_disallow_is_obeyed(public_dns: None) -> None:
    respx.get("https://example.com/robots.txt").respond(
        200,
        headers={"Content-Type": "text/plain"},
        text="User-agent: *\nDisallow: /private\n",
    )
    respx.get("https://example.com/private/page").respond(
        200, headers={"Content-Type": "text/html"}, text="secret"
    )
    with pytest.raises(SafeFetchError):
        safe_fetch("https://example.com/private/page", apply_rate_limit=False)


def test_rate_limit_waits_between_requests_to_same_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"t": 1000.0}
    slept: list[float] = []
    monkeypatch.setattr(sf.time, "time", lambda: clock["t"])
    monkeypatch.setattr(sf.time, "sleep", lambda s: slept.append(s))
    sf._domain_last_request.clear()
    sf.enforce_domain_rate_limit("example.com")
    clock["t"] += 0.25
    sf.enforce_domain_rate_limit("example.com")
    assert slept and slept[0] == pytest.approx(0.75)


# --- crawler chain ------------------------------------------------------------------------------


def test_crawler_refuses_internal_urls_before_launching_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_crawl4ai(url: str) -> str:
        calls.append(url)
        return "internal admin page contents"

    monkeypatch.setattr(crawl, "fetch_with_crawl4ai", fake_crawl4ai)
    with pytest.raises(SSRFSecurityError):
        crawl.crawl_page("http://127.0.0.1/admin")
    assert calls == []


def test_internal_links_stay_on_same_registered_domain() -> None:
    html = """
      <a href="/pricing">p</a>
      <a href="https://app.example.com/features">f</a>
      <a href="https://evil.com/pricing">x</a>
      <a href="javascript:alert(1)">j</a>
      <a href="mailto:a@example.com">m</a>
    """
    links = crawl.extract_internal_page_links("https://example.com", html)
    assert "https://example.com/pricing" in links
    assert all("evil.com" not in u for u in links)
    assert all(u.startswith(("http://", "https://")) for u in links)


def test_httpx_is_used_without_following_redirects_automatically() -> None:
    """Redirects must be followed manually so every hop is re-validated."""
    import inspect

    src = inspect.getsource(sf.safe_fetch)
    assert "follow_redirects=False" in src
    assert isinstance(httpx.Client(follow_redirects=False).follow_redirects, bool)
