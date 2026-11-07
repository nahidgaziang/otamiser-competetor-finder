"""Discovery run and research run end to end, with search and crawling replaced by fixtures."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest

from compare_pipeline import research
from compare_pipeline.db import get_pipeline_session
from compare_pipeline.discovery import discovery

TAG = uuid.uuid4().hex[:6]
EXISTING = f"existing-{TAG}.example"
NEW_A = f"newcomer-a-{TAG}.example"
NEW_B = f"newcomer-b-{TAG}.example"


class _Resp:
    def __init__(self, text: str):
        self.text = text


@pytest.fixture
def discovery_run(monkeypatch: pytest.MonkeyPatch, superuser: psycopg.Connection):  # noqa: ANN201
    superuser.execute(
        "INSERT INTO app.competitors (name, canonical_domain, status) VALUES ('Existing Co', %s, 'covered')",
        (EXISTING,),
    )
    hits = [
        {
            "title": "Existing Co pricing",
            "url": f"https://www.{EXISTING}/pricing",
            "snippet": "",
            "provider": "ddgs",
            "domain": EXISTING,
        },
        {
            "title": "Airbnb listing",
            "url": "https://www.airbnb.com/rooms/1",
            "snippet": "",
            "provider": "ddgs",
            "domain": "airbnb.com",
        },
        {
            "title": "G2 reviews",
            "url": "https://www.g2.com/x",
            "snippet": "",
            "provider": "ddgs",
            "domain": "g2.com",
        },
        {
            "title": "Newcomer A | Dynamic pricing",
            "url": f"https://{NEW_A}/",
            "snippet": "rev mgmt",
            "provider": "ddgs",
            "domain": NEW_A,
        },
        {
            "title": "Newcomer B - Revenue",
            "url": f"https://{NEW_B}/",
            "snippet": "rev mgmt",
            "provider": "ddgs",
            "domain": NEW_B,
        },
    ]
    monkeypatch.setattr(
        discovery,
        "load_query_config",
        lambda: ({"test": ["q1"]}, {"airbnb.com", "g2.com", "otamiser.com"}),
    )
    monkeypatch.setattr(
        discovery.SearchClient, "search", lambda self, q, max_results=8: hits
    )
    monkeypatch.setattr(
        discovery,
        "safe_fetch",
        lambda url, **_: _Resp(
            "<title>Newcomer | Home</title><h1>Dynamic pricing and revenue management for vacation rental hosts</h1>"
        ),
    )
    yield discovery.run_discovery(max_candidates=1)
    superuser.execute(
        "DELETE FROM app.competitors WHERE canonical_domain IN (%s, %s, %s)",
        (EXISTING, NEW_A, NEW_B),
    )
    superuser.execute("DELETE FROM app.discovery_hits WHERE query = 'q1'")


def test_discovery_records_every_search_hit(discovery_run: dict[str, Any]) -> None:
    assert discovery_run["total_discovery_hits"] == 5


def test_discovery_respects_max_candidates(discovery_run: dict[str, Any]) -> None:
    assert discovery_run["new_candidates_created"] == 1


def test_discovery_skips_blocklisted_and_known_competitors(
    discovery_run: dict[str, Any], superuser: psycopg.Connection
) -> None:
    domains = {c["domain"] for c in discovery_run["candidates"]}
    assert domains <= {NEW_A, NEW_B}
    rows = superuser.execute(
        "SELECT count(*) FROM app.competitors WHERE canonical_domain IN ('airbnb.com','g2.com') AND status='candidate'"
    ).fetchone()
    assert rows == (0,)


def test_discovery_stores_candidates_with_a_quote(
    discovery_run: dict[str, Any], superuser: psycopg.Connection
) -> None:
    row = superuser.execute(
        "SELECT status, evidence_quote FROM app.competitors WHERE canonical_domain IN (%s, %s) AND status='candidate'",
        (NEW_A, NEW_B),
    ).fetchone()
    assert row is not None and row[0] == "candidate" and "Dynamic pricing" in row[1]


# --- research --------------------------------------------------------------------------------------

PAGES = {
    "home": "Zentrix offers dynamic pricing for vacation rentals across Airbnb and Booking.com channels worldwide.",
    "pricing": "Simple pricing. Plans start at $19 per month for each listing. Start a 14-day free trial today.",
    "features": "Real-time rate optimisation powered by machine learning adjusts nightly prices automatically.",
}


@pytest.fixture
def crawled(monkeypatch: pytest.MonkeyPatch, competitor: uuid.UUID):  # noqa: ANN201
    def fake_crawl(url: str) -> tuple[str, str]:
        key = (
            "pricing"
            if "pricing" in url
            else "features"
            if "features" in url
            else "home"
        )
        return PAGES[key], "fixture"

    monkeypatch.setattr(research, "crawl_page", fake_crawl)
    monkeypatch.setattr(
        research,
        "extract_internal_page_links",
        lambda base, html, max_links=9: [f"{base}/pricing", f"{base}/features"],
    )
    with get_pipeline_session() as s:
        result = research.run_competitor_research(s, competitor)
    return result, competitor


def test_research_stores_one_snapshot_per_page(
    crawled, superuser: psycopg.Connection
) -> None:  # noqa: ANN001
    result, comp = crawled
    assert result["snapshots_collected"] == 3
    n = superuser.execute(
        "SELECT count(*) FROM app.source_snapshots WHERE competitor_id=%s", (comp,)
    ).fetchone()
    assert n == (3,)


def test_research_claims_point_at_their_snapshot_and_quote(
    crawled, superuser: psycopg.Connection
) -> None:  # noqa: ANN001
    _, comp = crawled
    rows = superuser.execute(
        "SELECT c.quote, s.content_markdown, c.status FROM app.claims c JOIN app.source_snapshots s ON s.id = c.snapshot_id WHERE c.competitor_id=%s",
        (comp,),
    ).fetchall()
    assert rows, "expected claims from the fixture pages"
    for quote, page, status in rows:
        assert status == "verified"
        assert " ".join(quote.split()).lower() in " ".join(page.split()).lower()


def test_research_with_too_few_pages_needs_attention(
    monkeypatch: pytest.MonkeyPatch,
    competitor: uuid.UUID,
    superuser: psycopg.Connection,
) -> None:
    monkeypatch.setattr(research, "crawl_page", lambda url: (PAGES["home"], "fixture"))
    monkeypatch.setattr(research, "extract_internal_page_links", lambda *a, **k: [])
    with get_pipeline_session() as s:
        research.run_competitor_research(s, competitor)
    assert superuser.execute(
        "SELECT status FROM app.competitors WHERE id=%s", (competitor,)
    ).fetchone() == ("needs_attention",)


def test_research_advances_competitor_status(
    crawled, superuser: psycopg.Connection
) -> None:  # noqa: ANN001
    _, comp = crawled
    assert superuser.execute(
        "SELECT status FROM app.competitors WHERE id=%s", (comp,)
    ).fetchone() == ("researched",)
