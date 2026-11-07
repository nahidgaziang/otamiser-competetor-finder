import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from compare_pipeline.gate import run_article_gate
from compare_pipeline.knowledge import get_baseline_facts, get_cta_config
from compare_pipeline.llm import LLMClient
from compare_pipeline.models import Article, ArticleVersion, Claim, Competitor
from compare_pipeline.models_article import ArticleDraft
from compare_pipeline.render import render_article_to_webflow_html

logger = logging.getLogger("generation")


def generate_comparison_draft(
    session: Session,
    competitor_id: uuid.UUID,
    job_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """
    Executes comparison article generation:
    1. Loads competitor and verified claims.
    2. Gathers baseline facts and CTA settings.
    3. Prompts LLM for structured ArticleDraft JSON.
    4. Evaluates through 10-point gate.
    5. Saves Article and ArticleVersion to PostgreSQL.
    """
    comp = session.query(Competitor).filter(Competitor.id == competitor_id).one()
    claims = (
        session.query(Claim)
        .filter(
            Claim.competitor_id == competitor_id,
            Claim.status == "verified",
        )
        .all()
    )
    facts = get_baseline_facts()
    cta = get_cta_config()

    logger.info(
        "Generating comparison draft for: %s with %d verified claims",
        comp.name,
        len(claims),
    )

    # Format claims and facts prompt
    claims_context = "\n".join(
        [f'- [ID: {c.id}] {c.field}: {c.value} (Quote: "{c.quote}")' for c in claims]
    )
    facts_context = "\n".join([f"- [ID: {f['id']}] {f['claim']}" for f in facts])

    prompt = f"""
Write a comprehensive, objective comparison article between Otamiser and {comp.name} ({comp.canonical_domain}).
Ensure every factual paragraph cites a claim_id or fact_id.
Prose length must be between 900 and 1,600 words.

Verified Competitor Claims:
{claims_context or "No custom claims, focus on general dynamic pricing architecture."}

Baseline Otamiser Public Facts:
{facts_context}

CTA Configuration:
Heading: {cta.get("heading")}
Description: {cta.get("description")}
Button: {cta.get("button_text")} -> {cta.get("button_url")}
"""

    llm = LLMClient()
    draft = llm.generate_structured(
        prompt=prompt,
        response_model=ArticleDraft,
        job_id=job_id,
        stage="generate",
    )

    # Render HTML
    webflow_html = render_article_to_webflow_html(draft)

    # Run 10-point gate
    gate_report = run_article_gate(draft, session=session, competitor_id=comp.id)
    logger.info("Gate evaluation for %s: all_passed=%s", comp.name, gate_report.passed)

    # Locate or create Article row
    slug = draft.slug or f"otamiser-vs-{comp.canonical_domain.split('.')[0]}"
    article = session.query(Article).filter(Article.competitor_id == comp.id).first()
    if not article:
        article = Article(
            id=uuid.uuid4(),
            competitor_id=comp.id,
            slug=slug,
            status="draft",
        )
        session.add(article)
        session.flush()

    # Determine version number
    prev_versions = (
        session.query(ArticleVersion)
        .filter(ArticleVersion.article_id == article.id)
        .count()
    )
    version_num = prev_versions + 1

    # Save ArticleVersion
    art_version = ArticleVersion(
        id=uuid.uuid4(),
        article_id=article.id,
        version_number=version_num,
        content=draft.model_dump(),
        webflow_html=webflow_html,
        gate_report=gate_report.to_dict(),
        gate_stale=False,
        source="ai_pipeline",
        model=llm.model_name,
    )
    session.add(art_version)
    session.flush()

    # Link current version
    article.current_version_id = art_version.id
    if not gate_report.passed:
        article.status = "needs_attention"
    else:
        article.status = "needs_review"

    session.commit()

    return {
        "article_id": str(article.id),
        "version_id": str(art_version.id),
        "version_number": version_num,
        "slug": article.slug,
        "gate_passed": gate_report.passed,
        "status": article.status,
    }
