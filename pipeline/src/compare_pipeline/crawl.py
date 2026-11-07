import hashlib
import logging
import re
import urllib.parse
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from compare_pipeline.discovery.dedupe import extract_canonical_domain
from compare_pipeline.http.safe_fetch import (
    safe_fetch,
)
from compare_pipeline.models import SourceSnapshot

logger = logging.getLogger("crawl")

# Page classification patterns
TIER_PATTERNS = [
    (re.compile(r"/(pricing|plans|rates|costs|packages|api|docs)", re.IGNORECASE), "A"),
    (
        re.compile(
            r"/(features|product|platform|solutions|how-it-works|services)",
            re.IGNORECASE,
        ),
        "B",
    ),
    (
        re.compile(
            r"/(case-studies|customers|testimonials|about|press|news)", re.IGNORECASE
        ),
        "C",
    ),
    (re.compile(r"/(blog|articles|resources|faq)", re.IGNORECASE), "D"),
]


def classify_source_tier(url: str) -> str:
    """Classifies a URL into source tiers A, B, C, or D."""
    path = urllib.parse.urlparse(url).path.lower()
    for pattern, tier in TIER_PATTERNS:
        if pattern.search(path):
            return tier
    return "B" if path in ("", "/") else "D"


def extract_internal_page_links(
    base_url: str, html: str, max_links: int = 15
) -> list[str]:
    """Finds high-priority internal links (pricing, features, about, docs)."""
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = extract_canonical_domain(parsed_base.netloc)

    found_urls: dict[str, int] = {}  # url -> priority

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        joined = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(joined)

        # Must match base canonical domain and use http/https
        if parsed.scheme.lower() not in ("http", "https"):
            continue
        if extract_canonical_domain(parsed.netloc) != base_domain:
            continue

        clean_path = parsed.path.rstrip("/")
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{clean_path}"
        if not clean_path:
            continue

        # Score priority
        priority = 0
        path_lower = clean_path.lower()
        if any(k in path_lower for k in ("pricing", "plan", "rate")):
            priority = 100
        elif any(
            k in path_lower for k in ("feature", "product", "platform", "solution")
        ):
            priority = 80
        elif any(k in path_lower for k in ("about", "company", "integration")):
            priority = 60
        elif any(k in path_lower for k in ("faq", "docs", "help")):
            priority = 40

        if normalized_url not in found_urls or priority > found_urls[normalized_url]:
            found_urls[normalized_url] = priority

    # Sort by priority descending
    sorted_links = sorted(found_urls.keys(), key=lambda u: found_urls[u], reverse=True)
    return sorted_links[:max_links]


async def fetch_with_crawl4ai(url: str) -> str | None:
    """Attempts headless browser rendering via Crawl4AI."""
    try:
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url)
            if result.success and result.markdown:
                return result.markdown
    except Exception as e:
        logger.warning("Crawl4AI failed for %s: %s", url, e)
    return None


def fetch_with_trafilatura(url: str) -> str | None:
    """Fallback text extraction via Trafilatura + safe_fetch."""
    try:
        import trafilatura

        resp = safe_fetch(url)
        extracted = trafilatura.extract(
            resp.text, include_links=True, include_tables=True
        )
        if extracted and len(extracted.strip()) > 50:
            return extracted
    except Exception as e:
        logger.warning("Trafilatura failed for %s: %s", url, e)
    return None


def crawl_page(url: str) -> tuple[str, str]:
    """
    Executes crawler chain:
    1. Crawl4AI (headless JS rendering)
    2. Trafilatura fallback
    3. Basic safe_fetch text fallback
    Returns: (content_markdown, fetcher_used)
    """
    import asyncio

    try:
        # Try Crawl4AI
        md = asyncio.run(fetch_with_crawl4ai(url))
        if md:
            return md, "crawl4ai"
    except Exception as e:
        logger.debug("Async crawl4ai execution error for %s: %s", url, e)

    # Try Trafilatura fallback
    traf_md = fetch_with_trafilatura(url)
    if traf_md:
        return traf_md, "trafilatura"

    # Basic fallback
    resp = safe_fetch(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    # Clean scripts/styles
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text, "safe_fetch_basic"


def record_snapshot(
    session: Session,
    competitor_id: Any | None,
    url: str,
    content: str,
    fetcher: str,
) -> SourceSnapshot:
    """Computes SHA-256 and stores snapshot idempotently in app.source_snapshots."""
    sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    tier = classify_source_tier(url)

    # Check existing snapshot by sha256 and url
    existing = (
        session.query(SourceSnapshot)
        .filter(
            SourceSnapshot.url == url,
            SourceSnapshot.sha256 == sha256_hash,
        )
        .first()
    )

    if existing:
        return existing

    snapshot = SourceSnapshot(
        competitor_id=competitor_id,
        url=url,
        source_tier=tier,
        fetcher=fetcher,
        content_markdown=content,
        sha256=sha256_hash,
    )
    session.add(snapshot)
    session.flush()
    return snapshot
