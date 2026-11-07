"""Shared helpers for the review test suites (tests/unit, tests/integration).

Defect IDs referenced here (BUG-xx) are documented in reports/code-review.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from compare_pipeline.llm import LLMClient
from compare_pipeline.models_article import ArticleDraft


def defect(bug_id: str, reason: str) -> pytest.MarkDecorator:
    """Marks a test that asserts correct behaviour but currently fails because of a known defect.

    xfail_strict is on, so once the defect is fixed the test XPASSes, the suite fails,
    and the marker must be removed. That keeps this list honest.
    """
    return pytest.mark.xfail(strict=True, reason=f"{bug_id}: {reason}")


def make_draft() -> ArticleDraft:
    """A schema-valid draft (the prototype's canned mock article), deep-copied so tests can mutate it."""
    return LLMClient()._create_mock_instance(ArticleDraft).model_copy(deep=True)


@dataclass
class FakeClaim:
    quote: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "verified"


class _FakeQuery:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """Minimal stand-in for a SQLAlchemy session as used by run_article_gate()."""

    def __init__(self, claims: list[FakeClaim] | None = None):
        self.claims = claims or []

    def query(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return _FakeQuery(self.claims)


def _with_real_claims(
    draft: ArticleDraft, quote: str = "A valid quote that is in the snapshot"
) -> tuple[ArticleDraft, FakeSession, uuid.UUID]:
    """Replace the mock's fake 'claim-sample-1' IDs with an ID the fake DB knows about."""
    claim = FakeClaim(quote=quote)
    cid = str(claim.id)
    for p in draft.competitor_overview:
        if p.claim_id:
            p.claim_id = cid
    for faq in draft.faqs:
        for p in faq.answer:
            if p.claim_id:
                p.claim_id = cid
    for cat in draft.comparison_table:
        for row in cat.rows:
            if row.competitor_cell.claim_id:
                row.competitor_cell.claim_id = cid
    return draft, FakeSession([claim]), uuid.uuid4()
