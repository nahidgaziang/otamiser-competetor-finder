from typing import Literal

from pydantic import BaseModel, Field


class TextRun(BaseModel):
    text: str
    bold: bool = False
    href: str | None = None


class SourcedParagraph(BaseModel):
    runs: list[TextRun]
    claim_id: str | None = None
    fact_id: str | None = None

    def get_plain_text(self) -> str:
        return "".join(run.text for run in self.runs)


class FeatureCell(BaseModel):
    state: Literal["yes", "no", "partial", "text"]
    text_content: str | None = None
    claim_id: str | None = None
    fact_id: str | None = None
    quote: str | None = None


class FeatureRow(BaseModel):
    feature_name: str
    competitor_cell: FeatureCell
    baseline_cell: FeatureCell


class TableCategory(BaseModel):
    category_name: str
    rows: list[FeatureRow] = Field(min_length=2)


class DifferenceSection(BaseModel):
    title: str
    paragraphs: list[SourcedParagraph]


class FAQItem(BaseModel):
    question: str
    answer: list[SourcedParagraph]


class ArticleDraft(BaseModel):
    title: str = Field(max_length=60, description="SEO Title under 60 characters")
    meta_description: str = Field(
        min_length=120,
        max_length=160,
        description="Meta description 120-160 characters",
    )
    slug: str
    competitor_name: str
    competitor_domain: str
    intro: list[SourcedParagraph] = Field(min_length=1, max_length=3)
    competitor_overview: list[SourcedParagraph]
    baseline_overview: list[SourcedParagraph]
    differences: list[DifferenceSection] = Field(min_length=2, max_length=5)
    comparison_table: list[TableCategory] = Field(min_length=3)
    who_is_it_for: list[SourcedParagraph] | None = None
    pricing_analysis: list[SourcedParagraph] | None = None
    results_impact: list[SourcedParagraph] | None = None
    faqs: list[FAQItem] = Field(min_length=4, max_length=6)
    cta_heading: str
    cta_description: str
    cta_button_text: str
    cta_button_url: str

    def get_full_prose_text(self) -> str:
        """Returns plain text of all prose sections for word count and gate analysis."""
        lines: list[str] = []
        for p in self.intro:
            lines.append(p.get_plain_text())
        for p in self.competitor_overview:
            lines.append(p.get_plain_text())
        for p in self.baseline_overview:
            lines.append(p.get_plain_text())
        for diff in self.differences:
            for p in diff.paragraphs:
                lines.append(p.get_plain_text())
        if self.who_is_it_for:
            for p in self.who_is_it_for:
                lines.append(p.get_plain_text())
        if self.pricing_analysis:
            for p in self.pricing_analysis:
                lines.append(p.get_plain_text())
        if self.results_impact:
            for p in self.results_impact:
                lines.append(p.get_plain_text())
        for faq in self.faqs:
            for p in faq.answer:
                lines.append(p.get_plain_text())
        return " ".join(lines)
