import nh3

from compare_pipeline.models_article import (
    ArticleDraft,
    SourcedParagraph,
    TableCategory,
    TextRun,
)

# Allowlist for Webflow Rich Text & Embedded Components
ALLOWED_TAGS = {
    "h2",
    "h3",
    "p",
    "strong",
    "em",
    "a",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "div",
    "span",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "target", "class"},
    "div": {"class"},
    "span": {"class"},
    "table": {"class"},
    "tr": {"class"},
    "th": {"class", "colspan"},
    "td": {"class"},
}


def sanitize_html(html_str: str) -> str:
    """Sanitizes HTML using nh3 allowlist."""
    return nh3.clean(
        html_str,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        link_rel="noopener noreferrer",
    )


def render_runs_to_html(runs: list[TextRun]) -> str:
    """Converts structured TextRuns to HTML text."""
    parts = []
    for run in runs:
        text = run.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if run.bold:
            text = f"<strong>{text}</strong>"
        if run.href:
            text = f'<a href="{run.href}">{text}</a>'
        parts.append(text)
    return "".join(parts)


def render_paragraphs_to_html(paragraphs: list[SourcedParagraph]) -> str:
    parts = []
    for p in paragraphs:
        inner = render_runs_to_html(p.runs)
        parts.append(f"<p>{inner}</p>")
    return "\n".join(parts)


def wrap_table_embed(table_html: str) -> str:
    """Wraps table markup with live component class wrapper."""
    return (
        f'<div class="otr-tnr"><div class="otr-table-wrapper">{table_html}</div></div>'
    )


def render_comparison_table_html(
    categories: list[TableCategory],
    competitor_name: str,
    baseline_name: str = "Otamiser",
) -> str:
    """Renders structured categories and feature rows into Webflow component table markup."""
    lines = [
        '<table class="otr-table">',
        "  <thead>",
        '    <tr class="section-row">',
        '      <th class="col-feature">Feature Comparison</th>',
        f'      <th class="col-c">{competitor_name}</th>',
        f'      <th class="col-o">{baseline_name}</th>',
        "    </tr>",
        "  </thead>",
        "  <tbody>",
    ]

    for cat in categories:
        lines.append(
            f'    <tr class="section-row"><th colspan="3">{cat.category_name}</th></tr>'
        )
        for row in cat.rows:
            # Competitor cell
            c_state = row.competitor_cell.state
            if c_state == "yes":
                c_markup = '<span class="check">✓</span>'
            elif c_state == "no":
                c_markup = '<span class="cross">✕</span>'
            elif c_state == "partial":
                txt = row.competitor_cell.text_content or "Partial"
                c_markup = f'<span class="partial-icon">▲</span><span class="cell-label-partial">{txt}</span>'
            else:
                c_markup = f"<span>{row.competitor_cell.text_content or ''}</span>"

            # Baseline cell
            b_state = row.baseline_cell.state
            if b_state == "yes":
                b_markup = '<span class="check">✓</span>'
            elif b_state == "no":
                b_markup = '<span class="cross">✕</span>'
            elif b_state == "partial":
                txt = row.baseline_cell.text_content or "Partial"
                b_markup = f'<span class="partial-icon">▲</span><span class="cell-label-partial">{txt}</span>'
            else:
                b_markup = f"<span>{row.baseline_cell.text_content or ''}</span>"

            lines.append(
                f'    <tr class="feature-row">'
                f'      <td class="col-feature">{row.feature_name}</td>'
                f'      <td class="col-c">{c_markup}</td>'
                f'      <td class="col-o">{b_markup}</td>'
                f"    </tr>"
            )

    lines.append("  </tbody>")
    lines.append("</table>")

    raw_table = "\n".join(lines)
    return wrap_table_embed(raw_table)


def render_article_to_webflow_html(draft: ArticleDraft) -> str:
    """
    Renders complete ArticleDraft JSON into Webflow Rich Text + Embedded table HTML.
    Sanitizes output through nh3.
    """
    sections = []

    # Intro
    sections.append(render_paragraphs_to_html(draft.intro))

    # Overviews
    sections.append(f"<h2>What {draft.competitor_name} Does</h2>")
    sections.append(render_paragraphs_to_html(draft.competitor_overview))

    sections.append("<h2>What Otamiser Does</h2>")
    sections.append(render_paragraphs_to_html(draft.baseline_overview))

    # Key Differences
    sections.append(f"<h2>Key Differences: Otamiser vs {draft.competitor_name}</h2>")
    for diff in draft.differences:
        sections.append(f"<h3>{diff.title}</h3>")
        sections.append(render_paragraphs_to_html(diff.paragraphs))

    # Comparison Table Embed
    table_html = render_comparison_table_html(
        draft.comparison_table, draft.competitor_name, "Otamiser"
    )
    sections.append(table_html)

    # Optional Who is it for
    if draft.who_is_it_for:
        sections.append("<h2>Who is Each Platform For?</h2>")
        sections.append(render_paragraphs_to_html(draft.who_is_it_for))

    # Optional Pricing Analysis
    if draft.pricing_analysis:
        sections.append("<h2>Pricing Comparison</h2>")
        sections.append(render_paragraphs_to_html(draft.pricing_analysis))

    # FAQs
    sections.append("<h2>Frequently Asked Questions</h2>")
    for faq in draft.faqs:
        sections.append(f"<h3>{faq.question}</h3>")
        sections.append(render_paragraphs_to_html(faq.answer))

    # Call to action
    sections.append(f"<h2>{draft.cta_heading}</h2>")
    sections.append(f"<p>{draft.cta_description}</p>")
    sections.append(
        f'<p><a href="{draft.cta_button_url}" class="cta-button">{draft.cta_button_text}</a></p>'
    )

    raw_html = "\n\n".join(sections)
    return sanitize_html(raw_html)
