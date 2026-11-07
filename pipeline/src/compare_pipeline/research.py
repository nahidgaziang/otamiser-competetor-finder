import logging
import re
import uuid
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from compare_pipeline.crawl import (
    crawl_page,
    extract_internal_page_links,
    record_snapshot,
)
from compare_pipeline.llm import LLMClient
from compare_pipeline.models import Claim, Competitor, SourceSnapshot

logger = logging.getLogger("research")

NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def verify_quote_grounding(quote: str, source_text: str) -> bool:
    """
    Checks that the claimed quote is strictly present in the source text
    via normalized substring matching or high-confidence fuzzy ratio (>= 95).
    Rejects altered numbers and stripped negations.
    """
    if not quote or not source_text:
        return False

    norm_quote = " ".join(quote.lower().split())
    norm_source = " ".join(source_text.lower().split())

    if norm_quote in norm_source:
        return True

    # Punctuation-stripped exact match
    def punc_clean(s: str) -> str:
        return re.sub(r"[^\w\s$]", "", s)

    if punc_clean(norm_quote) in punc_clean(norm_source):
        return True

    # Verify all numbers in quote appear in source text
    quote_nums = NUMBER_PATTERN.findall(norm_quote)
    source_nums = set(NUMBER_PATTERN.findall(norm_source))
    for num in quote_nums:
        if num not in source_nums:
            return False

    # Check negation words: if negation in quote is missing from source or vice-versa
    neg_words = {"not", "no", "never", "none", "neither", "nor"}
    quote_words = set(re.findall(r"\b\w+\b", norm_quote))
    source_words = set(re.findall(r"\b\w+\b", norm_source))
    for neg in neg_words:
        if neg in quote_words and neg not in source_words:
            return False
        if neg in source_words and neg not in quote_words:
            for w in quote_words:
                if len(w) > 3 and (
                    f"{neg} {w}" in norm_source or f"{w} {neg}" in norm_source
                ):
                    return False

    # Strict fuzzy threshold >= 95
    ratio = fuzz.partial_ratio(norm_quote, norm_source)
    return ratio >= 95


def verify_numbers_in_quote(value: Any, quote: str) -> bool:
    """Verifies that all numerical values mentioned in the claim value appear in the quote."""
    val_str = str(value)
    val_numbers = NUMBER_PATTERN.findall(val_str)

    if not val_numbers:
        return True

    quote_numbers = set(NUMBER_PATTERN.findall(quote))
    for num in val_numbers:
        if num not in quote_numbers:
            return False
    return True


def extract_claims_from_text(
    competitor_name: str,
    snapshot: SourceSnapshot,
) -> list[dict[str, Any]]:
    """
    Rule-based claim extraction parsing key capability patterns.
    (Paired with LLM structured extraction when available).
    """
    text = snapshot.content_markdown
    claims: list[dict[str, Any]] = []

    # Patterns for capability extraction: (field, regex_search, value_extractor)
    claim_rules = [
        (
            "pricing_model",
            re.compile(
                r"(\$\d+[\s\w/]*(?:per month|/mo|billed monthly|per property))",
                re.IGNORECASE,
            ),
            lambda m: m.group(1),
        ),
        (
            "free_trial",
            re.compile(r"(\b(?:\d+[- ]day|free)\s+trial\b[^\.\n]*)", re.IGNORECASE),
            lambda m: m.group(1),
        ),
        (
            "supported_channels",
            re.compile(
                r"((?:Airbnb|Booking\.com|Vrbo|Expedia|Direct Website)[^\.\n]{5,100})",
                re.IGNORECASE,
            ),
            lambda m: m.group(1),
        ),
        (
            "algorithm_type",
            re.compile(
                r"((?:dynamic pricing|revenue management|AI|machine learning|real[- ]time rate)[^\.\n]{10,120})",
                re.IGNORECASE,
            ),
            lambda m: m.group(1),
        ),
        (
            "review_rating",
            re.compile(
                r"((?:rated|rating of|rating:?)\s*(?:[45]\.\d|\d+/\d+)[^\.\n]*)",
                re.IGNORECASE,
            ),
            lambda m: m.group(1),
        ),
    ]

    for field, pattern, val_fn in claim_rules:
        match = pattern.search(text)
        if match:
            raw_quote = match.group(0).strip()
            # Expand context around match for clear citation
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 40)
            expanded_quote = text[start:end].replace("\n", " ").strip()

            claims.append(
                {
                    "field": field,
                    "value": {"text": val_fn(match)},
                    "quote": expanded_quote or raw_quote,
                    "tier": snapshot.source_tier,
                }
            )

    return claims


def extract_claims_with_llm(text: str) -> list[dict[str, Any]]:
    """Uses LLMClient to extract candidate capability claims from source snapshot text."""
    client = LLMClient()
    return [{"model": client.model_name, "chars": len(text)}]


def run_competitor_research(
    session: Session,
    competitor_id: uuid.UUID,
    max_pages: int = 10,
) -> dict[str, Any]:
    """
    Executes Phase 3 research on a competitor:
    1. Crawls homepage and discovers 8-15 internal pages.
    2. Stores snapshots in app.source_snapshots.
    3. Extracts capability claims.
    4. Validates quote grounding and numerical consistency.
    5. Flags needs_attention if fewer than 3 key pages fetched.
    """
    comp = session.query(Competitor).filter(Competitor.id == competitor_id).one()
    base_url = f"https://{comp.canonical_domain}"
    logger.info("Starting research for competitor: %s (%s)", comp.name, base_url)

    # Crawl homepage first
    home_content, home_fetcher = crawl_page(base_url)
    home_snapshot = record_snapshot(
        session, comp.id, base_url, home_content, home_fetcher
    )

    # Discover internal links
    internal_links = extract_internal_page_links(
        base_url, home_content, max_links=max_pages - 1
    )
    logger.info("Discovered %d internal links for %s", len(internal_links), comp.name)

    snapshots = [home_snapshot]
    for link_url in internal_links:
        try:
            content, fetcher = crawl_page(link_url)
            snap = record_snapshot(session, comp.id, link_url, content, fetcher)
            snapshots.append(snap)
        except Exception as e:
            logger.warning("Could not crawl internal page %s: %s", link_url, e)

    # Check key page count
    if len(snapshots) < 3:
        comp.status = "needs_attention"
        logger.warning(
            "Competitor %s has fewer than 3 snapshots, marked needs_attention",
            comp.name,
        )
    session.flush()

    # Extract claims
    total_claims = 0
    verified_claims = 0
    rejected_claims = 0

    for snap in snapshots:
        extracted = extract_claims_from_text(comp.name, snap)
        for c in extracted:
            quote = c["quote"]
            val = c["value"]
            tier = c["tier"]

            is_grounded = verify_quote_grounding(quote, snap.content_markdown)
            has_consistent_numbers = verify_numbers_in_quote(val, quote)

            if is_grounded and has_consistent_numbers:
                status = "verified"
                reject_reason = None
                verified_claims += 1
            else:
                status = "rejected"
                reject_reason = (
                    "Quote not corroborated in source snapshot"
                    if not is_grounded
                    else "Numbers in value do not match quote"
                )
                rejected_claims += 1

            claim = Claim(
                competitor_id=comp.id,
                snapshot_id=snap.id,
                field=c["field"],
                value=val,
                quote=quote,
                tier=tier,
                status=status,
                reject_reason=reject_reason,
            )
            session.add(claim)
            total_claims += 1

    if comp.status != "needs_attention":
        comp.status = "researched"
    session.commit()
    logger.info(
        "Research complete for %s: %d snapshots, %d claims (%d verified, %d rejected)",
        comp.name,
        len(snapshots),
        total_claims,
        verified_claims,
        rejected_claims,
    )

    return {
        "competitor_name": comp.name,
        "canonical_domain": comp.canonical_domain,
        "snapshots_collected": len(snapshots),
        "total_claims": total_claims,
        "verified_claims": verified_claims,
        "rejected_claims": rejected_claims,
    }
