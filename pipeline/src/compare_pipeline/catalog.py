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
            is_listicle = not ("otamiser-vs-" in slug or "vs-" in slug)

            if is_listicle:
                listicles_count += 1
                # Listicles stored as covered category competitor or mentioned
                name = raw_title or slug.replace("-", " ").title()
                domain = f"{slug}.otamiser-topic.internal"
                status = "mentioned"
            else:
                name = clean_competitor_name(raw_title, slug)
                # Infer default domain from slug
                domain_name = slug.split("vs-")[-1].replace("-", "")
                domain = f"{domain_name}.com"
                status = "covered"

            # Check if competitor exists by canonical domain
            canon_domain = extract_canonical_domain(domain)
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
                    status=status,
                    summary=f"Discovered from public Otamiser comparison page: {path}",
                    segment="Vacation Rental / Hotel Revenue Management",
                    type="direct" if not is_listicle else "listicle_topic",
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
                    status="published" if status == "covered" else "draft",
                )
                # Since pipeline_rw cannot set status='published', we leave status as 'draft' or insert via SQL if needed
                # Note: db trigger blocks pipeline_rw from setting status='published'.
                art.status = "draft"
                session.add(art)
                session.flush()

            seeded_count += 1

            # Fetch reference articles text if matching
            if slug in REFERENCE_SLUGS:
                ref_filename = REFERENCE_SLUGS[slug]
                ref_path = REFERENCES_DIR / ref_filename
                logger.info(
                    "Extracting style reference article for %s -> %s",
                    slug,
                    ref_filename,
                )
                try:
                    ref_res = safe_fetch(f"https://www.otamiser.com{path}")
                    ref_soup = BeautifulSoup(ref_res.text, "html.parser")
                    # Extract main article body text
                    main_elem = (
                        ref_soup.find("main")
                        or ref_soup.find("article")
                        or ref_soup.body
                    )
                    if main_elem:
                        ref_text = main_elem.get_text(separator="\n", strip=True)
                        ref_path.write_text(ref_text, encoding="utf-8")
                        logger.info(
                            "Saved reference article (%d chars) to %s",
                            len(ref_text),
                            ref_path,
                        )
                except Exception as e:
                    logger.warning("Could not fetch reference %s: %s", slug, e)

    return {
        "total_pages_discovered": len(unique_entries),
        "seeded_competitors": seeded_count,
        "listicles_count": listicles_count,
    }
