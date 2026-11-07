"""Quality gate (validation goal V7; proposal 4.7, build guide 9.5)."""

from __future__ import annotations

import uuid

import pytest
from helpers import FakeClaim, FakeSession, make_draft

from compare_pipeline.gate import run_article_gate
from compare_pipeline.models_article import SourcedParagraph, TextRun


def _with_real_claims(draft, quote: str = "Plans start at $19 per month."):  # noqa: ANN001, ANN202
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


def _gate(draft, session=None, competitor_id=None):  # noqa: ANN001, ANN202
    return run_article_gate(draft, session=session, competitor_id=competitor_id)


def test_well_formed_draft_with_known_sources_passes() -> None:
    draft, session, comp = _with_real_claims(make_draft())
    report = _gate(draft, session, comp)
    failed = {k: v for k, v in report.checks.items() if not v["passed"]}
    # cross_grounding is excluded here because BUG-G5 makes the mock itself non-compliant.
    failed.pop("cross_grounding", None)
    assert failed == {}


def test_report_serialises_with_overall_flag() -> None:
    report = _gate(make_draft())
    d = report.to_dict()
    assert set(d) == {"all_passed", "checks"}
    assert all({"passed", "details"} <= set(v) for v in d["checks"].values())


def test_unknown_fact_id_is_rejected() -> None:
    draft = make_draft()
    draft.intro[0].fact_id = "fact-that-does-not-exist"
    assert _gate(draft).checks["claims_verified"]["passed"] is False


def test_unsourced_intro_paragraph_is_rejected() -> None:
    draft = make_draft()
    draft.intro[0].fact_id = None
    draft.intro[0].claim_id = None
    assert _gate(draft).checks["sourcing_complete"]["passed"] is False


def test_invented_large_number_is_rejected() -> None:
    draft = make_draft()
    draft.intro[0].runs[0].text += " Bookings rise by 999.8 percent."
    assert _gate(draft).checks["number_grounding"]["passed"] is False


@pytest.mark.parametrize("token", ["TODO", "TBD", "lorem ipsum", "Competitor X"])
def test_placeholders_are_rejected(token: str) -> None:
    draft = make_draft()
    draft.differences[0].paragraphs[0].runs[0].text += f" {token}"
    assert _gate(draft).checks["no_placeholders"]["passed"] is False


def test_banned_hype_words_are_rejected() -> None:
    draft = make_draft()
    draft.differences[0].paragraphs[0].runs[0].text += " A revolutionary game-changer."
    assert _gate(draft).checks["style_lint"]["passed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "x" * 61),
        ("meta_description", "Too short."),
        ("slug", "Has Spaces And CAPS"),
    ],
)
def test_metadata_limits_are_enforced(field: str, value: str) -> None:
    draft = make_draft()
    object.__setattr__(draft, field, value)  # bypass pydantic validation on assignment
    assert _gate(draft).checks["metadata_rules"]["passed"] is False


def test_prose_shorter_than_900_words_is_rejected() -> None:
    draft = make_draft()
    short = SourcedParagraph(runs=[TextRun(text="Short.")], fact_id="fact-ota-ranking")
    draft.intro = [short]
    draft.competitor_overview = [short]
    draft.baseline_overview = [short]
    draft.who_is_it_for = None
    draft.pricing_analysis = None
    draft.results_impact = None
    assert _gate(draft).checks["word_count"]["passed"] is False


# --- confirmed defects ---------------------------------------------------------------------------


def test_claim_sample_ids_are_not_trusted() -> None:
    draft = make_draft()  # mock cites 'claim-sample-1', which does not exist
    report = _gate(draft, FakeSession([]), uuid.uuid4())
    assert report.checks["claims_verified"]["passed"] is False


def test_gate_fails_closed_when_claims_cannot_be_verified() -> None:
    draft = make_draft()
    draft.competitor_overview[0].claim_id = str(uuid.uuid4())
    assert _gate(draft).checks["claims_verified"]["passed"] is False


def test_unsourced_faq_answer_is_rejected() -> None:
    draft, session, comp = _with_real_claims(make_draft())
    draft.faqs[0].answer[0].fact_id = None
    draft.faqs[0].answer[0].claim_id = None
    assert _gate(draft, session, comp).checks["sourcing_complete"]["passed"] is False


def test_unsourced_optional_section_is_rejected() -> None:
    draft, session, comp = _with_real_claims(make_draft())
    draft.pricing_analysis = [
        SourcedParagraph(runs=[TextRun(text="Costs about the same.")])
    ]
    assert _gate(draft, session, comp).checks["sourcing_complete"]["passed"] is False


def test_unsourced_table_cell_is_rejected() -> None:
    draft, session, comp = _with_real_claims(make_draft())
    cell = draft.comparison_table[1].rows[0].competitor_cell
    cell.state = "yes"
    cell.claim_id = None
    cell.fact_id = None
    assert _gate(draft, session, comp).checks["sourcing_complete"]["passed"] is False


def test_cross_without_explicit_evidence_is_rejected() -> None:
    draft, session, comp = _with_real_claims(make_draft())
    report = _gate(draft, session, comp)
    assert report.checks["cross_grounding"]["passed"] is False


def test_cross_with_unverified_inline_quote_is_rejected() -> None:
    draft, session, comp = _with_real_claims(make_draft())
    cell = draft.comparison_table[0].rows[0].competitor_cell
    cell.text_content = "No"
    cell.quote = "They definitely do not do this."  # invented by the model
    report = _gate(draft, session, comp)
    assert report.checks["cross_grounding"]["passed"] is False


def test_number_must_match_whole_number_in_cited_quote() -> None:
    draft, session, comp = _with_real_claims(
        make_draft(), quote="Plans start at $399 per year."
    )
    draft.competitor_overview[0].runs[0].text += " It costs $39 per month."
    assert _gate(draft, session, comp).checks["number_grounding"]["passed"] is False


def test_small_prices_are_still_grounded() -> None:
    draft, session, comp = _with_real_claims(make_draft())
    draft.competitor_overview[0].runs[0].text += " It costs $5 per listing."
    assert _gate(draft, session, comp).checks["number_grounding"]["passed"] is False


def test_slug_must_follow_otamiser_vs_pattern() -> None:
    draft = make_draft()
    object.__setattr__(draft, "slug", "best-pricing-tools")
    assert _gate(draft).checks["metadata_rules"]["passed"] is False


def test_gate_includes_ai_checker_result() -> None:
    assert "ai_checker" in _gate(make_draft()).checks
