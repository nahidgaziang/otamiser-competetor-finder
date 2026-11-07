"""What happens AFTER a paid model call: the answer must never be lost, and failures must be explained.

The live test has a budget of one call, so a refusal, a cut-off answer or a schema slip (e.g. a 165-character
meta description) has to produce a clear error and a saved copy of the answer that can be replayed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest
from helpers import make_draft

from compare_pipeline import llm
from compare_pipeline.llm import LLMClient, LLMResponseError
from compare_pipeline.models_article import ArticleDraft

PIPELINE = Path(__file__).resolve().parents[2]


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Fake SDK client returning whatever `state['reply']` holds; records logged calls."""
    state: dict[str, Any] = {"logged": []}

    class _Client:
        def __init__(self, **_: Any):
            self.messages = self

        def create(self, **_: Any) -> Any:
            text, stop = state["reply"]
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="thinking", thinking=""),
                    SimpleNamespace(type="text", text=text),
                ],
                stop_reason=stop,
                stop_details={"category": "test"} if stop == "refusal" else None,
                usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
            )

    monkeypatch.setattr(anthropic, "Anthropic", _Client)
    monkeypatch.setattr(llm, "get_current_spend_usd", lambda: 0.0)
    monkeypatch.setattr(llm, "LAST_RESPONSE_PATH", tmp_path / "last.json")
    monkeypatch.setattr(
        LLMClient, "_log_call", lambda self, **kw: state["logged"].append(kw)
    )
    state["path"] = tmp_path / "last.json"
    return state


def _client() -> LLMClient:
    c = LLMClient()
    c.api_key = "sk-test"
    return c


def test_valid_answer_is_returned_and_saved(fake_api: dict[str, Any]) -> None:
    good = make_draft().model_dump_json()
    fake_api["reply"] = (good, "end_turn")
    draft = _client().generate_structured(prompt="p", response_model=ArticleDraft)
    assert draft.title == make_draft().title
    assert fake_api["path"].read_text(encoding="utf-8") == good
    assert len(fake_api["logged"]) == 1


def test_schema_slip_names_the_field_and_keeps_the_paid_answer(
    fake_api: dict[str, Any],
) -> None:
    bad = json.loads(make_draft().model_dump_json())
    bad["meta_description"] = "Too short."
    fake_api["reply"] = (json.dumps(bad), "end_turn")
    with pytest.raises(LLMResponseError, match="meta_description"):
        _client().generate_structured(prompt="p", response_model=ArticleDraft)
    assert (
        json.loads(fake_api["path"].read_text(encoding="utf-8"))["meta_description"]
        == "Too short."
    )
    assert len(fake_api["logged"]) == 1, "the call is still recorded (it was billed)"


def test_refusal_is_reported_as_refusal(fake_api: dict[str, Any]) -> None:
    fake_api["reply"] = ("", "refusal")
    with pytest.raises(LLMResponseError, match="refusal"):
        _client().generate_structured(prompt="p", response_model=ArticleDraft)
    assert len(fake_api["logged"]) == 1


def test_cut_off_answer_is_reported_as_truncated(fake_api: dict[str, Any]) -> None:
    fake_api["reply"] = ('{"title": "Otamiser vs', "max_tokens")
    with pytest.raises(LLMResponseError, match="max_tokens"):
        _client().generate_structured(prompt="p", response_model=ArticleDraft)
    assert fake_api["path"].read_text(encoding="utf-8").startswith('{"title"')


def test_prompt_states_the_hard_limits() -> None:
    src = (PIPELINE / "src" / "compare_pipeline" / "generation.py").read_text(
        encoding="utf-8"
    )
    for limit in (
        "at most 60 characters",
        "between 120 and 160 characters",
        "at least 3 categories",
        "4 to 6",
    ):
        assert limit in src


def test_replay_rejects_an_invalid_file_before_touching_the_database(
    tmp_path: Path,
) -> None:
    """--from-file validates first, so a half-fixed file can't create a broken draft."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"title": "x"}', encoding="utf-8")
    run = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "scripts/live_generate_once.py",
            "--domain",
            "x.example",
            "--name",
            "X",
            "--from-file",
            str(bad),
        ],
        cwd=PIPELINE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode != 0
    assert "ValidationError" in run.stderr
    assert "[1/4]" not in run.stdout
