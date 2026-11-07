from compare_pipeline.crawl import classify_source_tier, extract_internal_page_links
from compare_pipeline.research import (
    verify_numbers_in_quote,
    verify_quote_grounding,
)


def test_quote_grounding_verification():
    """Validates Goal V5: Verbatim quotes are verified; fabricated quotes are rejected."""
    snapshot_text = """
    PriceLabs provides dynamic pricing and revenue management tools for vacation rentals.
    Our starter plan begins at $19.99 per month with no credit card required.
    We connect directly with Airbnb, Booking.com, and Vrbo to adjust rates daily.
    """

    # Authentic quotes
    assert (
        verify_quote_grounding(
            "Our starter plan begins at $19.99 per month with no credit card required.",
            snapshot_text,
        )
        is True
    )

    assert (
        verify_quote_grounding(
            "PriceLabs provides dynamic pricing and revenue management tools",
            snapshot_text,
        )
        is True
    )

    # Fabricated quotes (V5 test cases)
    fabricated_quotes = [
        "PriceLabs offers an unconditional 90-day money-back guarantee.",
        "Guaranteed 50% increase in revenue within the first 30 days.",
        "Completely free for enterprise hotel chains with over 500 units.",
        "Exclusive partnership with Expedia that guarantees top ranking.",
        "Zero setup fees and free 24/7 dedicated telephone support.",
    ]

    for fab_quote in fabricated_quotes:
        assert verify_quote_grounding(fab_quote, snapshot_text) is False


def test_number_consistency_in_quote():
    """Validates that quantitative numbers in claim value exist in cited quote."""
    # Authentic match
    quote = "Plans start at $19 per month with a 30-day free trial."
    assert verify_numbers_in_quote({"price": 19, "trial": "30-day"}, quote) is True

    # Fabricated / hallucinated numbers
    quote_no_num = "We offer flexible monthly subscriptions with a generous trial."
    assert verify_numbers_in_quote({"price": 29}, quote_no_num) is False

    quote_different_num = "Our pricing is $49 per unit."
    assert verify_numbers_in_quote({"price": 19}, quote_different_num) is False


def test_source_tier_classification():
    """Validates source tiering (A: pricing/docs, B: features, C: case studies, D: blog/faq)."""
    assert classify_source_tier("https://example.com/pricing") == "A"
    assert classify_source_tier("https://example.com/plans") == "A"
    assert classify_source_tier("https://example.com/api/v1") == "A"
    assert classify_source_tier("https://example.com/features") == "B"
    assert classify_source_tier("https://example.com/product") == "B"
    assert classify_source_tier("https://example.com/case-studies/hotel-x") == "C"
    assert classify_source_tier("https://example.com/blog/2026-trends") == "D"


def test_extract_internal_page_links():
    """Validates that internal links are correctly prioritized and external links are ignored."""
    base = "https://example.com"
    html = """
    <html>
      <body>
        <a href="/pricing">Pricing</a>
        <a href="/features/dynamic-rates">Features</a>
        <a href="/blog/hello">Blog</a>
        <a href="https://external.com/affiliate">External</a>
        <a href="/about-us">About Us</a>
      </body>
    </html>
    """
    links = extract_internal_page_links(base, html, max_links=10)
    assert "https://example.com/pricing" in links
    assert "https://example.com/features/dynamic-rates" in links
    assert "https://example.com/about-us" in links
    assert not any("external.com" in link for link in links)
    # Pricing should be prioritized first
    assert links[0] == "https://example.com/pricing"
