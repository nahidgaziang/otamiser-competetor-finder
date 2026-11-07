from compare_pipeline.gate import run_article_gate
from compare_pipeline.llm import LLMClient
from compare_pipeline.models_article import ArticleDraft
from compare_pipeline.render import render_article_to_webflow_html


def test_gate_valid_draft_passes_all_checks():
    """Validates that a compliant ArticleDraft passes all 10 gate checks."""
    llm = LLMClient()
    draft = llm._create_mock_instance(ArticleDraft)

    from helpers import _with_real_claims

    draft, session, comp = _with_real_claims(draft)
    report = run_article_gate(draft, session=session, competitor_id=comp)
    for check_name in [
        "sourcing_complete",
        "schema_valid",
        "word_count",
        "metadata_rules",
        "style_lint",
        "no_placeholders",
        "html_valid",
    ]:
        assert report.checks[check_name]["passed"] is True, (
            f"Check '{check_name}' failed: {report.checks[check_name]['details']}"
        )


def test_gate_detects_unsourced_paragraphs():
    """Validates Goal V7: Gate catches unsourced factual claims."""
    llm = LLMClient()
    draft = llm._create_mock_instance(ArticleDraft)

    # Remove source attribution from intro paragraph
    draft.intro[0].fact_id = None
    draft.intro[0].claim_id = None

    report = run_article_gate(draft)
    assert report.passed is False
    assert report.checks["sourcing_complete"]["passed"] is False


def test_gate_detects_hallucinated_numbers():
    """Validates Goal V7: Gate catches unverified numerical metrics in prose."""
    llm = LLMClient()
    draft = llm._create_mock_instance(ArticleDraft)

    # Inject uncorroborated numerical figure
    draft.intro[0].runs[0].text += " Increases bookings by 999.8% guaranteed."

    report = run_article_gate(draft)
    assert report.passed is False
    assert report.checks["number_grounding"]["passed"] is False


def test_gate_detects_placeholders():
    """Validates Goal V7: Gate rejects placeholder tokens."""
    llm = LLMClient()
    draft = llm._create_mock_instance(ArticleDraft)

    # Inject placeholder
    draft.differences[0].paragraphs[0].runs[0].text += " [TODO: Add pricing detail]"

    report = run_article_gate(draft)
    assert report.passed is False
    assert report.checks["no_placeholders"]["passed"] is False


def test_gate_detects_style_lint_buzzwords():
    """Validates Goal V7: Gate catches forbidden hyperbole."""
    llm = LLMClient()
    draft = llm._create_mock_instance(ArticleDraft)

    # Inject banned buzzword
    draft.differences[0].paragraphs[0].runs[
        0
    ].text += " A truly revolutionary algorithm."

    report = run_article_gate(draft)
    assert report.passed is False
    assert report.checks["style_lint"]["passed"] is False


def test_gate_detects_invalid_metadata():
    """Validates Goal V7: Gate enforces title length limit (<= 60 chars)."""
    llm = LLMClient()
    draft = llm._create_mock_instance(ArticleDraft)

    # Make title excessive (> 60 chars)
    draft.title = "This is an extremely long title that exceeds sixty characters easily and will fail the gate check"

    report = run_article_gate(draft)
    assert report.passed is False
    assert report.checks["metadata_rules"]["passed"] is False


def test_html_render_sanitization():
    """Validates that render_article_to_webflow_html sanitizes scripts and dangerous tags."""
    llm = LLMClient()
    draft = llm._create_mock_instance(ArticleDraft)

    html = render_article_to_webflow_html(draft)
    assert "<table" in html
    assert 'class="otr-table"' in html
    assert "<script" not in html
    assert "<iframe" not in html
