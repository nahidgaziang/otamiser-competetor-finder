import re

import tldextract
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from compare_pipeline.models import Competitor

# Common corporate/entity suffixes to strip during normalization
CORP_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|technologies|technology|software|app|pms|co)\b",
    re.IGNORECASE,
)


def extract_canonical_domain(url_or_domain: str) -> str:
    """Extracts the registered domain (e.g. 'app.pricelabs.co' -> 'pricelabs.co')."""
    ext = tldextract.extract(url_or_domain)
    if not ext.suffix:
        # Fallback if bare name
        return url_or_domain.lower().strip()
    return f"{ext.domain}.{ext.suffix}".lower()


def normalize_company_name(name: str) -> str:
    """Normalizes company name for fuzzy comparison."""
    # Remove corporate suffixes and non-alphanumeric characters
    cleaned = CORP_SUFFIXES.sub("", name)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return " ".join(cleaned.lower().split())


def is_duplicate_competitor(
    candidate_name: str,
    candidate_domain_or_url: str,
    candidate_aliases: list[str] | None = None,
    existing_competitors: list[Competitor] | None = None,
    session: Session | None = None,
    fuzzy_threshold: float = 85.0,
) -> tuple[bool, str | None, str | None]:
    """
    Evaluates whether a candidate competitor already exists based on:
    1. Exact canonical domain match
    2. Known alias domain or name match
    3. High-confidence fuzzy string match (rapidfuzz >= 85)
    Returns: (is_duplicate, matched_name_or_domain, reason)
    """
    candidate_domain = extract_canonical_domain(candidate_domain_or_url)
    norm_candidate_name = normalize_company_name(candidate_name)
    all_candidate_aliases = [
        normalize_company_name(a) for a in (candidate_aliases or [])
    ]

    # Load competitors if not provided
    if existing_competitors is None:
        if session is None:
            raise ValueError("Either existing_competitors or session must be provided")
        existing_competitors = session.query(Competitor).all()

    for comp in existing_competitors:
        # 1. Exact canonical domain match
        if comp.canonical_domain and candidate_domain == comp.canonical_domain.lower():
            return True, comp.name, f"exact_domain_match ({candidate_domain})"

        # 2. Check aliases for domain or name match
        norm_comp_name = normalize_company_name(comp.name)
        comp_aliases_norm = [normalize_company_name(a) for a in (comp.aliases or [])]

        if candidate_domain in [
            extract_canonical_domain(a) for a in (comp.aliases or [])
        ]:
            return True, comp.name, f"alias_domain_match ({candidate_domain})"

        if norm_candidate_name in comp_aliases_norm:
            return True, comp.name, f"alias_name_match ({comp.name})"

        for cand_alias in all_candidate_aliases:
            if cand_alias and cand_alias == norm_comp_name:
                return True, comp.name, f"candidate_alias_matches_name ({comp.name})"

        # 3. Fuzzy string matching on normalized names (rapidfuzz token_sort_ratio >= 85)
        score = fuzz.token_sort_ratio(norm_candidate_name, norm_comp_name)
        if score >= fuzzy_threshold:
            return (
                True,
                comp.name,
                f"fuzzy_name_match (score={score:.1f} >= {fuzzy_threshold})",
            )

    return False, None, None
