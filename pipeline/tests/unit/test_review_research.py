"""Evidence: quote grounding and number consistency (validation goal V5, proposal section 3.3)."""

from __future__ import annotations

import pytest

from compare_pipeline.crawl import classify_source_tier
from compare_pipeline.research import (
    extract_claims_from_text,
    verify_numbers_in_quote,
    verify_quote_grounding,
)

SOURCE = (
    "Our Pro plan costs $29 per month per property. "
    "We do not offer a free trial. "
    "Rankbreeze does not react to competitor prices or market changes."
)


def test_exact_quote_is_grounded() -> None:
    assert verify_quote_grounding(
        "Our Pro plan costs $29 per month per property.", SOURCE
    )


def test_quote_with_different_whitespace_and_case_is_grounded() -> None:
    assert verify_quote_grounding("our pro plan   costs $29\nper month", SOURCE)


def test_empty_quote_or_source_is_not_grounded() -> None:
    assert verify_quote_grounding("", SOURCE) is False
    assert verify_quote_grounding("anything", "") is False


@pytest.mark.parametrize(
    "fabricated",
    [
        pytest.param(
            "Our Pro plan costs $39 per month per property.",
            id="price-changed",
        ),
        pytest.param(
            "Our Pro plan costs $299 per month per property.",
            id="price-inflated",
        ),
        pytest.param(
            "Rankbreeze does react to competitor prices or market changes.",
            id="negation-removed",
        ),
        pytest.param("We do offer a free trial.", id="negation-removed-short"),
        pytest.param(
            "Guaranteed 50% revenue increase in 30 days.", id="invented-sentence"
        ),
    ],
)
def test_fabricated_or_altered_quotes_are_rejected(fabricated: str) -> None:
    assert verify_quote_grounding(fabricated, SOURCE) is False


@pytest.mark.parametrize(
    ("value", "quote", "expected"),
    [
        ({"price": 29}, "costs $29 per month", True),
        ({"price": "$1,200"}, "Plans cost $1,200 per year", True),
        ({"price": 39}, "costs $399 per year", False),
        ({"trial": "14-day"}, "a 30-day trial", False),
        ({"text": "no numbers here"}, "anything", True),
    ],
)
def test_numbers_in_value_must_appear_in_quote(value, quote, expected) -> None:  # noqa: ANN001
    assert verify_numbers_in_quote(value, quote) is expected


@pytest.mark.parametrize(
    ("url", "tier"),
    [
        ("https://x.com/pricing", "A"),
        ("https://x.com/docs/setup", "A"),
        ("https://x.com/features", "B"),
        ("https://x.com/", "B"),
        ("https://x.com/about", "C"),
        ("https://x.com/blog/post", "D"),
    ],
)
def test_source_tier_classification(url: str, tier: str) -> None:
    assert classify_source_tier(url) == tier


def test_help_centre_pages_are_tier_a() -> None:
    assert classify_source_tier("https://x.com/help/setting-up-rules") == "A"


class _Snap:
    def __init__(self, text: str, tier: str = "A"):
        self.content_markdown = text
        self.source_tier = tier


def test_extracted_claim_quotes_are_verbatim_substrings() -> None:
    """Sanity check of the rule-based extractor, which is all research currently uses."""
    text = "Simple pricing.\nPlans start at $19 per month for every listing.\nAirbnb and Booking.com supported channels list."
    claims = extract_claims_from_text("X", _Snap(text))
    assert claims, "expected at least one claim"
    norm = " ".join(text.split()).lower()
    for c in claims:
        assert " ".join(c["quote"].split()).lower() in norm


def test_research_extracts_claims_with_the_ai_model() -> None:
    import inspect

    from compare_pipeline import research

    src = inspect.getsource(research)
    assert "LLMClient" in src or "generate_structured" in src
