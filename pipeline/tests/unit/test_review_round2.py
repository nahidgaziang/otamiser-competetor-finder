"""Second review round (2026-11-07, after the 'Bug Fixed' commit).

These tests check behaviour, not source text: several earlier tests only looked for a string such as
"LLMClient" in a module, and that was satisfied without the model ever being called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anthropic
import pytest
import yaml
from helpers import defect, make_draft

from compare_pipeline import gate, llm
from compare_pipeline.llm import LLMClient
from compare_pipeline.models_article import ArticleDraft

ROOT = Path(__file__).resolve().parents[3]


def _walk(node: Any):  # noqa: ANN202
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# --- the request actually sent to the API ----------------------------------------------------------


@pytest.fixture
def captured_request(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sent: dict[str, Any] = {}

    class _Client:
        def __init__(self, **_: Any):
            self.messages = self

        def create(self, **kwargs: Any) -> Any:
            sent.update(kwargs)
            raise RuntimeError("stop before network")

    monkeypatch.setattr(anthropic, "Anthropic", _Client)
    monkeypatch.setattr(llm, "get_current_spend_usd", lambda: 0.0)
    c = LLMClient()
    c.api_key = "sk-test"
    with pytest.raises(RuntimeError):
        c.generate_structured("prompt", ArticleDraft)
    return sent


def test_schema_sent_to_api_uses_the_supported_dialect(
    captured_request: dict[str, Any],
) -> None:
    """Regression for BUG-L7: raw Pydantic schemas (minLength, no additionalProperties) get HTTP 400."""
    schema = captured_request["output_config"]["format"]["schema"]
    for node in _walk(schema):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False, node.get("title")
        assert "minLength" not in node and "maxLength" not in node
        assert node.get("minItems", 0) in (0, 1)


def test_output_budget_and_model(captured_request: dict[str, Any]) -> None:
    assert captured_request["max_tokens"] >= 16_000
    assert captured_request["model"] == "claude-haiku-5-5"


# --- fake implementations that satisfied string checks -----------------------------------------------


@defect(
    "BUG-G8b",
    "the 'ai_checker' gate check always records passed=True without calling a model",
)
def test_ai_checker_actually_calls_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_generate(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("stage", "?"))
        raise RuntimeError("checker unavailable")

    monkeypatch.setattr(LLMClient, "generate_structured", fake_generate)
    report = gate.run_article_gate(make_draft())
    assert calls, "the AI checker never called the model"
    assert report.checks["ai_checker"]["passed"] is False, (
        "a checker that could not run must not pass"
    )


# --- Otamiser facts --------------------------------------------------------------------------------


def _sitemap_paths() -> set[str]:
    lines = (
        (ROOT / "fixtures" / "otamiser_sitemap_paths.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


@defect(
    "BUG-K1b",
    "fact source URLs /features and /about do not exist on otamiser.com (both 404); citations were invented",
)
def test_fact_sources_are_real_otamiser_pages() -> None:
    facts = yaml.safe_load(
        (ROOT / "facts" / "otamiser-facts.yaml").read_text(encoding="utf-8")
    )
    paths = _sitemap_paths()
    for fact in facts["brand"]["facts"]:
        path = urlparse(fact["source_url"]).path.rstrip("/") or "/"
        assert path in paths, (
            f"{fact['id']}: {fact['source_url']} is not a page on otamiser.com"
        )


def test_sitemap_fixture_is_present() -> None:
    assert "/about-us" in _sitemap_paths() and "/pricing" in _sitemap_paths()


# --- found by a real crawl of rankbreeze.com (fixtures were tidy HTML, real input is Markdown) --------

REAL_MARKDOWN = """[ ![Rankbreeze dark logo](https://rankbreeze.com/wp-content/uploads/logo.svg) ](https://rankbreeze.com/)
* [Features](https://rankbreeze.com/features/)
* [Pricing](https://rankbreeze.com/pricing/)
* [About](https://rankbreeze.com/about-us/)
[ ![Airbnb icon](https://rankbreeze.com/wp-content/uploads/2025/10/airbnb-icon.svg) Airbnb ](https://rankbreeze.com/airbnb/)
Rankbreeze helps hosts track Airbnb search rankings every day.
"""


@defect(
    "BUG-R5",
    "Crawl4AI returns Markdown but link discovery only parses HTML <a> tags, so research stops at the homepage",
)
def test_internal_links_are_found_in_crawler_markdown() -> None:
    from compare_pipeline.crawl import extract_internal_page_links

    links = extract_internal_page_links("https://rankbreeze.com", REAL_MARKDOWN)
    assert any("/pricing" in u for u in links) and any("/features" in u for u in links)


@defect(
    "BUG-R6",
    "regex claims are cut from raw Markdown, so 'verified' quotes are navigation and image syntax",
)
def test_claim_quotes_contain_no_markup() -> None:
    from compare_pipeline.research import extract_claims_from_text

    class _Snap:
        content_markdown = REAL_MARKDOWN
        source_tier = "B"

    for claim in extract_claims_from_text("Rankbreeze", _Snap()):
        assert "![" not in claim["quote"] and "](http" not in claim["quote"], claim[
            "quote"
        ]
