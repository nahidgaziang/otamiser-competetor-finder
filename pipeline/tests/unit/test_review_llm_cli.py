"""AI layer (V6/V8; proposal 6.4, guide 9.7) and the CLI entry point."""

from __future__ import annotations

import sys
from contextlib import contextmanager, suppress
from types import SimpleNamespace
from typing import Any

import pytest
from helpers import make_draft

from compare_pipeline import llm
from compare_pipeline.llm import (
    LLMClient,
    SpendCapExceededError,
    calculate_call_cost,
    load_model_config,
)
from compare_pipeline.models_article import ArticleDraft


@pytest.fixture
def no_db(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Isolate the LLM client from the database: spend starts at $0 and calls are recorded in memory."""
    logged: list[dict[str, Any]] = []
    monkeypatch.setattr(llm, "get_current_spend_usd", lambda: 0.0)
    monkeypatch.setattr(LLMClient, "_log_call", lambda self, **kw: logged.append(kw))
    return logged


class _FakeAnthropic:
    """Captures the request; returns a text block (optionally preceded by a thinking block)."""

    last_kwargs: dict[str, Any] = {}
    calls = 0
    thinking_first = False

    def __init__(self, **_: Any):
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        _FakeAnthropic.last_kwargs = kwargs
        _FakeAnthropic.calls += 1
        text = SimpleNamespace(type="text", text=make_draft().model_dump_json())
        thinking = SimpleNamespace(type="thinking", thinking="", signature="sig")
        return SimpleNamespace(
            content=[thinking, text] if _FakeAnthropic.thinking_first else [text],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=2000),
            stop_reason="end_turn",
        )


@pytest.fixture
def fake_anthropic(
    monkeypatch: pytest.MonkeyPatch, no_db: list
) -> type[_FakeAnthropic]:
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    _FakeAnthropic.last_kwargs = {}
    _FakeAnthropic.calls = 0
    _FakeAnthropic.thinking_first = False
    return _FakeAnthropic


def _client() -> LLMClient:
    c = LLMClient()
    c.api_key = "sk-test"
    return c


def test_cost_is_computed_from_configured_prices() -> None:
    cfg = load_model_config()["models"]["claude-haiku-5-5"]
    expected = cfg["prompt_price_per_million"] + cfg["completion_price_per_million"]
    assert calculate_call_cost(
        "claude-haiku-5-5", 1_000_000, 1_000_000
    ) == pytest.approx(expected)


def test_configured_prices_match_published_prices() -> None:
    models = load_model_config()["models"]
    assert models["claude-haiku-5-5"]["prompt_price_per_million"] == pytest.approx(0.10)
    assert models["claude-haiku-5-5"]["completion_price_per_million"] == pytest.approx(
        0.50
    )
    assert models["claude-sonnet-5-5"]["prompt_price_per_million"] == pytest.approx(
        2.00
    )
    assert models["claude-sonnet-5-5"]["completion_price_per_million"] == pytest.approx(
        10.00
    )


def test_spend_cap_blocks_calls_that_would_exceed_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "get_current_spend_usd", lambda: 4.99)
    with pytest.raises(SpendCapExceededError):
        LLMClient().check_spend_cap(estimated_cost=0.05)


def test_spend_cap_allows_calls_under_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "get_current_spend_usd", lambda: 1.00)
    LLMClient().check_spend_cap(estimated_cost=0.05)


def test_missing_api_key_fails_instead_of_inventing_content(no_db: list) -> None:
    c = LLMClient()
    c.api_key = ""
    with pytest.raises(Exception):  # noqa: B017
        c.generate_structured("prompt", ArticleDraft)


def test_text_block_is_found_after_a_thinking_block(fake_anthropic: type) -> None:
    fake_anthropic.thinking_first = True
    draft = _client().generate_structured("prompt", ArticleDraft)
    assert isinstance(draft, ArticleDraft)


def test_request_constrains_output_to_the_schema(fake_anthropic: type) -> None:
    with suppress(Exception):  # only the request shape matters here
        _client().generate_structured("prompt", ArticleDraft)
    assert "output_config" in fake_anthropic.last_kwargs


def test_output_budget_fits_a_full_article(fake_anthropic: type) -> None:
    with suppress(Exception):
        _client().generate_structured("prompt", ArticleDraft)
    assert fake_anthropic.last_kwargs.get("max_tokens", 0) >= 16_000


def test_oversized_prompt_is_refused_before_calling(fake_anthropic: type) -> None:
    huge = "word " * 500_000
    with pytest.raises(Exception):  # noqa: B017
        _client().generate_structured(huge, ArticleDraft)
    assert fake_anthropic.calls == 0


def test_valid_response_is_parsed(fake_anthropic: type) -> None:
    assert isinstance(
        _client().generate_structured("prompt", ArticleDraft), ArticleDraft
    )


def test_call_is_logged_even_when_parsing_fails(
    fake_anthropic: type, no_db: list
) -> None:
    fake_anthropic.thinking_first = True
    with suppress(Exception):
        _client().generate_structured("prompt", ArticleDraft)
    assert len(no_db) == 1


def test_every_call_is_logged(fake_anthropic: type, no_db: list) -> None:
    with suppress(Exception):
        _client().generate_structured("prompt", ArticleDraft)
    assert len(no_db) == 1 and no_db[0]["stage"] == "generate"


# --- CLI -------------------------------------------------------------------------------------------


def _run_cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict[str, Any]:
    from compare_pipeline import __main__ as cli

    captured: dict[str, Any] = {}

    @contextmanager
    def fake_session():  # noqa: ANN202
        yield None

    def fake_request_job(session, kind, payload, requested_by):  # noqa: ANN001, ANN202
        captured.update(kind=kind, payload=payload, requested_by=requested_by)
        return "00000000-0000-0000-0000-000000000000"

    monkeypatch.setattr(cli, "get_pipeline_session", fake_session)
    monkeypatch.setattr(cli, "request_job", fake_request_job)
    monkeypatch.setattr(sys, "argv", ["compare_pipeline", *argv])
    cli.main()
    return captured


def test_cli_research_passes_competitor_id(monkeypatch: pytest.MonkeyPatch) -> None:
    got = _run_cli(monkeypatch, "run", "research", "--competitor-id", "c-1")
    assert got == {
        "kind": "research",
        "payload": {"competitor_id": "c-1"},
        "requested_by": "cli",
    }


def test_cli_gate_passes_article_id(monkeypatch: pytest.MonkeyPatch) -> None:
    got = _run_cli(monkeypatch, "run", "gate", "--article-id", "a-1")
    assert got["payload"] == {"article_id": "a-1"}


def test_cli_push_webflow_passes_article_id(monkeypatch: pytest.MonkeyPatch) -> None:
    got = _run_cli(monkeypatch, "run", "push-webflow", "--article-id", "a-1")
    assert got == {
        "kind": "push_webflow",
        "payload": {"article_id": "a-1"},
        "requested_by": "cli",
    }


def test_cli_seed_catalog_kind_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run_cli(monkeypatch, "run", "seed-catalog")["kind"] == "seed_catalog"
