"""Search provider fallback chain (V3; proposal 6.2) and the exported article schema."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from compare_pipeline import search
from compare_pipeline.models_article import ArticleDraft
from compare_pipeline.search import SearchClient

ROOT = Path(__file__).resolve().parents[3]


class _Ddgs:
    results: list[dict[str, Any]] | Exception = []

    def __enter__(self) -> _Ddgs:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def text(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        if isinstance(_Ddgs.results, Exception):
            raise _Ddgs.results
        return _Ddgs.results


class _Tavily:
    calls = 0

    def __init__(self, api_key: str):
        assert api_key

    def search(self, query: str, max_results: int = 10) -> dict[str, Any]:
        _Tavily.calls += 1
        return {
            "results": [
                {
                    "title": "Zentrix",
                    "url": "https://www.zentrix.io/pricing",
                    "content": "snippet",
                }
            ]
        }


class _Exa:
    calls = 0

    def __init__(self, api_key: str):
        assert api_key

    def search(self, query: str, num_results: int = 10) -> SimpleNamespace:
        _Exa.calls += 1
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    url="https://app.novarm.com/", title="NovaRM", text="x" * 500
                )
            ]
        )


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> None:
    import ddgs
    import exa_py
    import tavily

    monkeypatch.setattr(ddgs, "DDGS", _Ddgs)
    monkeypatch.setattr(tavily, "TavilyClient", _Tavily)
    monkeypatch.setattr(exa_py, "Exa", _Exa)
    _Ddgs.results = []
    _Tavily.calls = _Exa.calls = 0


def _client(tavily_key: str = "", exa_key: str = "") -> SearchClient:
    c = SearchClient()
    c.tavily_key, c.exa_key = tavily_key, exa_key
    return c


def test_ddgs_results_are_normalised(providers: None) -> None:
    _Ddgs.results = [
        {
            "title": "PriceLabs",
            "href": "https://app.pricelabs.co/x",
            "body": "dynamic pricing",
        }
    ]
    res = _client("t", "e").search("q")
    assert res == [
        {
            "title": "PriceLabs",
            "url": "https://app.pricelabs.co/x",
            "snippet": "dynamic pricing",
            "provider": "ddgs",
            "domain": "pricelabs.co",
        }
    ]
    assert _Tavily.calls == 0, (
        "fallbacks must not be called when the primary provider succeeds"
    )


def test_results_without_url_are_skipped(providers: None) -> None:
    _Ddgs.results = [{"title": "no url"}, {"title": "ok", "href": "https://ok.com"}]
    assert [r["url"] for r in _client().search("q")] == ["https://ok.com"]


def test_falls_back_to_tavily_when_ddgs_errors(providers: None) -> None:
    _Ddgs.results = RuntimeError("rate limited")
    res = _client(tavily_key="t", exa_key="e").search("q")
    assert [r["provider"] for r in res] == ["tavily"] and res[0][
        "domain"
    ] == "zentrix.io"
    assert _Exa.calls == 0


def test_falls_back_to_tavily_when_ddgs_returns_nothing(providers: None) -> None:
    assert _client(tavily_key="t").search("q")[0]["provider"] == "tavily"


def test_falls_back_to_exa_without_tavily_key(providers: None) -> None:
    _Ddgs.results = RuntimeError("blocked")
    res = _client(exa_key="e").search("q")
    assert res[0]["provider"] == "exa" and res[0]["domain"] == "novarm.com"
    assert len(res[0]["snippet"]) <= 300


def test_no_provider_available_returns_empty_list(providers: None) -> None:
    _Ddgs.results = RuntimeError("down")
    assert _client().search("q") == []


def test_search_module_reads_keys_from_settings() -> None:
    assert hasattr(search, "settings")


def test_committed_article_schema_matches_the_model() -> None:
    committed = json.loads(
        (ROOT / "schemas" / "article.schema.json").read_text(encoding="utf-8")
    )
    assert committed == ArticleDraft.model_json_schema(), (
        "run: python -m compare_pipeline export-schema"
    )
