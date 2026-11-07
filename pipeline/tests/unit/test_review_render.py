"""Webflow HTML renderer and sanitiser (proposal 4.3 / 5.4, build guide 9.6)."""

from __future__ import annotations

import re

from helpers import make_draft

from compare_pipeline.models_article import TextRun
from compare_pipeline.render import (
    render_article_to_webflow_html,
    render_comparison_table_html,
    render_runs_to_html,
    sanitize_html,
)

ALLOWED_TAGS = {
    "h2", "h3", "p", "strong", "em", "a", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "div", "span",
}  # fmt: skip


def _tags(html: str) -> set[str]:
    return {t.lower() for t in re.findall(r"<\s*([a-zA-Z0-9]+)", html)}


def test_output_uses_only_allowlisted_tags() -> None:
    html = render_article_to_webflow_html(make_draft())
    assert _tags(html) <= ALLOWED_TAGS


def test_never_emits_pre_or_code_blocks() -> None:
    html = render_article_to_webflow_html(make_draft())
    assert "<pre" not in html and "<code" not in html


def test_model_text_is_escaped_not_interpreted() -> None:
    draft = make_draft()
    draft.comparison_table[0].rows[0].feature_name = "Plans <$50> & AT&T"
    draft.competitor_name = 'Evil"Co<img src=x onerror=alert(1)>'
    draft.differences[0].title = "<script>alert(1)</script>Real title"
    html = render_article_to_webflow_html(draft)
    assert "Plans &lt;$50&gt; &amp; AT&amp;T" in html
    assert "onerror" not in html.lower()
    assert "<script" not in html.lower()
    assert "<img" not in html.lower()


def test_dangerous_link_schemes_are_removed() -> None:
    html = render_runs_to_html([TextRun(text="click", href="javascript:alert(1)")])
    assert "javascript:" not in sanitize_html(f"<p>{html}</p>")


def test_event_handler_attributes_are_stripped() -> None:
    assert "onclick" not in sanitize_html('<p onclick="x()">y</p>')


def test_links_get_noopener() -> None:
    out = sanitize_html('<a href="https://example.com">x</a>')
    assert 'rel="noopener noreferrer"' in out


def test_table_keeps_component_class_after_sanitising() -> None:
    html = render_article_to_webflow_html(make_draft())
    assert 'class="otr-tnr"' in html


def test_cell_states_render_expected_symbols() -> None:
    table = render_comparison_table_html(make_draft().comparison_table, "Comp")
    assert '<span class="check">✓</span>' in table
    assert '<span class="cross">✕</span>' in table
    assert "cell-label-partial" in table


def test_table_embed_is_far_below_webflow_limit() -> None:
    table = render_comparison_table_html(make_draft().comparison_table, "Comp")
    assert len(table) < 50_000


# --- confirmed deviations from Otamiser's live markup ----------------------------------------------


def test_otamiser_column_comes_first() -> None:
    table = render_comparison_table_html(make_draft().comparison_table, "Zentrix")
    header = table.split("</thead>")[0]
    assert header.index("Otamiser") < header.index("Zentrix")


def test_table_uses_live_component_class_names() -> None:
    table = render_comparison_table_html(make_draft().comparison_table, "Comp")
    for cls in ("th-empty", "th-otamiser", "th-competitor", "th-name", "feature-name"):
        assert f'class="{cls}"' in table, cls


def test_partial_cell_uses_svg_icon() -> None:
    table = render_comparison_table_html(make_draft().comparison_table, "Comp")
    assert "▲" not in table


def test_faq_questions_use_bold_paragraphs() -> None:
    draft = make_draft()
    html = render_article_to_webflow_html(draft)
    q = draft.faqs[0].question
    assert f"<p><strong>{q}</strong></p>" in html


def test_cta_is_not_part_of_article_body() -> None:
    html = render_article_to_webflow_html(make_draft())
    assert "cta-button" not in html


def test_results_section_is_rendered() -> None:
    from compare_pipeline.models_article import SourcedParagraph

    draft = make_draft()
    marker = "Results marker: occupancy rose in the pilot."
    draft.results_impact = [
        SourcedParagraph(runs=[TextRun(text=marker)], fact_id="fact-ota-ranking")
    ]
    assert marker in render_article_to_webflow_html(draft)


def test_differences_heading_matches_house_format() -> None:
    assert "<h2>Where the two differ</h2>" in render_article_to_webflow_html(
        make_draft()
    )
