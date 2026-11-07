import logging
import uuid
import yaml
import re
from pathlib import Path
from typing import Dict, Any, List, Set
from bs4 import BeautifulSoup
from compare_pipeline.search import SearchClient
from compare_pipeline.http.safe_fetch import safe_fetch, SafeFetchError, SSRFSecurityError
from compare_pipeline.discovery.dedupe import extract_canonical_domain, is_duplicate_competitor
from compare_pipeline.db import get_pipeline_session
from compare_pipeline.models import Competitor, DiscoveryHit

logger = logging.getLogger("discovery")

_PROTOTYPE_ROOT = Path(__file__).resolve().parents[4]
QUERIES_FILE = _PROTOTYPE_ROOT / "style" / "queries.yaml"

RELEVANCE_KEYWORDS = re.compile(
    r"\b(dynamic pricing|revenue management|pricing tool|rate optimization|short term rental|vacation rental|airbnb|booking\.com|yield management|hotel pricing)\b",
    re.IGNORECASE,
)


def load_query_config() -> tuple[Dict[str, List[str]], Set[str]]:
    """Loads query clusters and blocklist domains from style/queries.yaml."""
    if not QUERIES_FILE.exists():
        logger.warning("Queries config %s not found, using defaults", QUERIES_FILE)
        return (
            {"default": ["best short term rental dynamic pricing software"]},
            {"google.com", "bing.com", "otamiser.com", "airbnb.com"},
        )

    with open(QUERIES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    clusters = data.get("query_clusters", {})
    blocklist = set(data.get("blocklist_domains", []))
    return clusters, blocklist


def extract_homepage_evidence(html: str) -> tuple[str, str, float]:
    """
    Parses homepage HTML to extract:
    - Company name/title
    - Verbatim evidence quote mentioning pricing/revenue capabilities
    - Initial relevance score (0.0 to 1.0)
    """
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else "Unknown Provider"

    # Search for hero, h1, h2, or paragraph containing core value proposition
    evidence_quote = ""
    candidate_elements = soup.find_all(["h1", "h2", "p", "div"], limit=50)

    for el in candidate_elements:
        text = el.get_text(separator=" ", strip=True)
        if len(text) > 30 and len(text) < 300:
            if RELEVANCE_KEYWORDS.search(text):
                evidence_quote = text
                break

    # Calculate relevance score based on keyword density
    text_corpus = soup.get_text(separator=" ", strip=True).lower()
    matches = len(RELEVANCE_KEYWORDS.findall(text_corpus))
    score = min(1.0, 0.4 + (matches * 0.05))

    return title, evidence_quote, score


def run_discovery(max_candidates: int = 5) -> Dict[str, Any]:
    """
    Executes automated competitor discovery:
    1. Runs search queries from query clusters.
    2. Filters blocklist domains.
    3. Deduplicates against existing competitors (canonical domain + fuzzy).
    4. Fetches candidate homepages via safe_fetch and extracts evidence.
    5. Stores up to max_candidates in app.competitors with status 'candidate'.
    """
    clusters, blocklist = load_query_config()
    search_client = SearchClient()

    total_hits = 0
    candidate_urls: Dict[str, Dict[str, Any]] = {}

    with get_pipeline_session() as session:
        # Load existing competitors for deduplication
        existing_comps = session.query(Competitor).all()

        for cluster_name, queries in clusters.items():
            for q in queries:
                logger.info("Executing discovery query [%s]: '%s'", cluster_name, q)
                results = search_client.search(q, max_results=8)
                for r in results:
                    domain = r["domain"]
                    url = r["url"]

                    # Log discovery hit
                    hit = DiscoveryHit(
                        id=uuid.uuid4(),
                        query=q,
                        provider=r["provider"],
                        url=url,
                        title=r["title"],
                        snippet=r["snippet"],
                        domain=domain,
                        raw_json=r,
                    )
                    session.add(hit)
                    total_hits += 1

                    # Skip blocklisted domains
                    if domain in blocklist or any(domain.endswith("." + b) for b in blocklist):
                        continue

                    # Deduplicate
                    is_dup, matched_name, _ = is_duplicate_competitor(
                        candidate_name=r["title"],
                        candidate_domain_or_url=domain,
                        existing_competitors=existing_comps,
                    )
                    if not is_dup and domain not in candidate_urls:
                        candidate_urls[domain] = {
                            "domain": domain,
                            "url": f"https://{domain}",
                            "title": r["title"],
                            "snippet": r["snippet"],
                        }

        logger.info("Identified %d unique potential candidates after deduplication", len(candidate_urls))

        # Inspect and classify candidates
        created_candidates = []
        for domain, info in list(candidate_urls.items()):
            if len(created_candidates) >= max_candidates:
                break

            target_url = info["url"]
            try:
                logger.info("Classifying candidate homepage: %s", target_url)
                resp = safe_fetch(target_url, timeout_sec=10.0)
                title, quote, score = extract_homepage_evidence(resp.text)

                # Clean name from title
                name_clean = title.split("-")[0].split("|")[0].strip() or domain

                new_comp = Competitor(
                    id=uuid.uuid4(),
                    name=name_clean,
                    canonical_domain=domain,
                    status="candidate",
                    relevance_score=score,
                    summary=info["snippet"] or f"Discovered via search: {title}",
                    evidence_quote=quote,
                    segment="Vacation Rental / Hotel Revenue Management",
                    type="direct",
                )
                session.add(new_comp)
                created_candidates.append({
                    "name": name_clean,
                    "domain": domain,
                    "relevance_score": score,
                    "evidence_quote": quote[:100] + "..." if len(quote) > 100 else quote,
                })
                logger.info("Added candidate competitor: %s (%s)", name_clean, domain)
            except (SafeFetchError, SSRFSecurityError, Exception) as e:
                logger.warning("Could not safely inspect candidate %s: %s", target_url, e)

        session.commit()

    return {
        "total_discovery_hits": total_hits,
        "new_candidates_created": len(created_candidates),
        "candidates": created_candidates,
    }
