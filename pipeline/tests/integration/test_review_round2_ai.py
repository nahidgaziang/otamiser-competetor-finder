"""Second review round: research and discovery must really use the model (proposal 2.3, 3.3).

Earlier tests only checked that "LLMClient" appeared in the source. These run the real functions and
record whether the model was called.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from helpers import defect

from compare_pipeline import research
from compare_pipeline.db import get_pipeline_session
from compare_pipeline.discovery import discovery
from compare_pipeline.llm import LLMClient


@pytest.fixture
def model_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake_generate(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("stage", "?"))
        raise RuntimeError("model unavailable in this test")

    monkeypatch.setattr(LLMClient, "generate_structured", fake_generate)
    return calls


@defect(
    "BUG-R3b",
    "extract_claims_with_llm() returns a dummy dict and is never called; research still uses regex only",
)
def test_research_calls_the_model_for_extraction(
    monkeypatch: pytest.MonkeyPatch, competitor: uuid.UUID, model_calls: list[str]
) -> None:
    page = "Plans start at $19 per month for each listing. Dynamic pricing for vacation rentals worldwide."
    monkeypatch.setattr(research, "crawl_page", lambda url: (page, "fixture"))
    monkeypatch.setattr(
        research,
        "extract_internal_page_links",
        lambda base, html, max_links=9: [f"{base}/pricing", f"{base}/features"],
    )
    try:
        with get_pipeline_session() as s:
            research.run_competitor_research(s, competitor)
    except Exception:  # noqa: BLE001, S110 - only whether the model was asked matters
        pass
    assert model_calls, "research never asked the model to extract claims"


@defect(
    "BUG-D1b",
    "classify_candidate_with_llm() uses the keyword regex and is never called by run_discovery()",
)
def test_discovery_calls_the_model_to_classify(
    monkeypatch: pytest.MonkeyPatch,
    superuser: psycopg.Connection,
    model_calls: list[str],
) -> None:
    domain = f"round2-{uuid.uuid4().hex[:6]}.example"
    hit = {
        "title": "Round2 Co",
        "url": f"https://{domain}/",
        "snippet": "",
        "provider": "ddgs",
        "domain": domain,
    }
    monkeypatch.setattr(
        discovery, "load_query_config", lambda: ({"t": ["round2-q"]}, set())
    )
    monkeypatch.setattr(
        discovery.SearchClient, "search", lambda self, q, max_results=8: [hit]
    )

    class _Resp:
        text = "<title>Round2</title><h1>Dynamic pricing and revenue management for vacation rentals</h1>"

    monkeypatch.setattr(discovery, "safe_fetch", lambda url, **_: _Resp())
    try:
        discovery.run_discovery(max_candidates=1)
    except Exception:  # noqa: BLE001, S110 - only whether the model was asked matters
        pass
    finally:
        superuser.execute(
            "DELETE FROM app.competitors WHERE canonical_domain = %s", (domain,)
        )
        superuser.execute("DELETE FROM app.discovery_hits WHERE query = 'round2-q'")
    assert model_calls, "discovery never asked the model to classify the candidate"
