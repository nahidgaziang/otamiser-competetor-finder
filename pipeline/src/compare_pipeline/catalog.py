import logging
import re
import uuid
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from compare_pipeline.db import get_pipeline_session
from compare_pipeline.discovery.dedupe import extract_canonical_domain
from compare_pipeline.http.safe_fetch import safe_fetch
from compare_pipeline.models import Article, Competitor

logger = logging.getLogger("catalog")

# Root directory of style references
_PROTOTYPE_ROOT = Path(__file__).resolve().parents[3]
REFERENCES_DIR = _PROTOTYPE_ROOT / "style" / "references"

REFERENCE_SLUGS = {
    "otamiser-vs-rankbreeze": "rankbreeze.txt",
    "otamiser-vs-the-net-revenue": "the_net_revenue.txt",
    "otamiser-vs-revolvio": "revolvio.txt",
}


def clean_competitor_name(raw_title: str, slug: str) -> str:
    """Extracts competitor name from title or slug."""
    # Pattern: 'Otamiser vs [Name]' or 'Otamiser Hotel Revenue Management vs [Name]'
    match = re.search(r"vs\.?\s+(.+?)(?:\s+\(202\d\)|$)", raw_title, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        # Clean any trailing punctuation
        return re.sub(r"[\s\-_]+", " ", name)

    # Fallback to slug: 'otamiser-vs-name'
    slug_match = re.search(r"vs-(.+)$", slug)
    if slug_match:
        return slug_match.group(1).replace("-", " ").title()

    return raw_title.strip()


def seed_catalog() -> dict[str, Any]:
    """
    Fetches https://www.otamiser.com/compare through safe_fetch,
    extracts all 41 comparison pages, populates competitors and articles in DB,
    and extracts plain text for the 3 reference articles.
    """
    logger.info("Fetching public hub https://www.otamiser.com/compare...")
    res = safe_fetch("https://www.otamiser.com/compare")
    soup = BeautifulSoup(res.text, "html.parser")

    all_links = soup.find_all("a", href=re.compile(r"^/compare/"))
    unique_entries: dict[str, str] = {}
    for a in all_links:
        href = a.get("href", "").strip().rstrip("/")
        title = a.get_text(strip=True)
        if href and href not in unique_entries and href != "/compare":
            unique_entries[href] = title

    logger.info(
        "Discovered %d unique comparison pages on Otamiser hub", len(unique_entries)
    )

    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    seeded_count = 0
    listicles_count = 0

    with get_pipeline_session() as session:
        for path, raw_title in unique_entries.items():
            slug = path.replace("/compare/", "")
            is_one_to_one = slug.startswith("otamiser-vs-") and slug.count("-vs-") == 1

            if not is_one_to_one:
                listicles_count += 1
                continue

            page_res = None
            page_soup = None
            try:
                page_res = safe_fetch(f"https://www.otamiser.com{path}")
                if page_res:
                    page_soup = BeautifulSoup(page_res.text, "html.parser")
            except Exception as e:
                logger.warning("Could not fetch comparison page %s: %s", path, e)

            # Find outbound competitor link on page
            domain = None
            if page_soup:
                for link in page_soup.find_all("a", href=True):
                    href = link["href"].strip()
                    if href.startswith("http://") or href.startswith("https://"):
                        d = extract_canonical_domain(href)
                        if d and "otamiser" not in d and not d.endswith(".internal"):
                            domain = d
                            break

            if not domain:
                domain_name = slug.replace("otamiser-vs-", "").replace("-", "")
                domain = f"{domain_name}.com"

            if "otamiser" in domain.lower():
                continue

            name = clean_competitor_name(raw_title, slug)
            if "otamiser" in name.lower() and not (" " in name or len(name) > 10):
                continue

            canon_domain = extract_canonical_domain(domain)
            if (
                not canon_domain
                or canon_domain.endswith(".internal")
                or "otamiser" in canon_domain
            ):
                continue

            comp = (
                session.query(Competitor)
                .filter(Competitor.canonical_domain == canon_domain)
                .first()
            )
            if not comp:
                comp = Competitor(
                    id=uuid.uuid4(),
                    name=name,
                    canonical_domain=canon_domain,
                    status="covered",
                    summary=f"Discovered from public Otamiser comparison page: {path}",
                    segment="Vacation Rental / Hotel Revenue Management",
                    type="direct",
                )
                session.add(comp)
                session.flush()

            # Ensure article draft row exists
            art = session.query(Article).filter(Article.slug == slug).first()
            if not art:
                art = Article(
                    id=uuid.uuid4(),
                    competitor_id=comp.id,
                    slug=slug,
                    status="draft",
                )
                session.add(art)
                session.flush()

            seeded_count += 1

            # Fetch reference articles text if matching
            if slug in REFERENCE_SLUGS:
                ref_filename = REFERENCE_SLUGS[slug]
                ref_path = REFERENCES_DIR / ref_filename
                if page_soup:
                    main_elem = (
                        page_soup.find("main")
                        or page_soup.find("article")
                        or page_soup.body
                    )
                    if main_elem:
                        ref_text = main_elem.get_text(separator="\n", strip=True)
                        ref_path.write_text(ref_text, encoding="utf-8")
                        logger.info(
                            "Saved reference article (%d chars) to %s",
                            len(ref_text),
                            ref_path,
                        )

    return {
        "total_pages_discovered": len(unique_entries),
        "seeded_competitors": seeded_count,
        "listicles_count": listicles_count,
    }
