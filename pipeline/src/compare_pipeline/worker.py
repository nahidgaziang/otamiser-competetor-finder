import logging
import signal
import time
from collections.abc import Callable
from typing import Any

from compare_pipeline.db import get_pipeline_session
from compare_pipeline.jobs import (
    claim_job,
    complete_job,
    fail_job,
    reap_stale_jobs,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("worker")

# Handler registry: maps job.kind to function(job_payload) -> (result_dict, Optional[chain_tuple])
JOB_HANDLERS: dict[
    str,
    Callable[
        [dict[str, Any]], tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]
    ],
] = {}


def register_handler(kind: str):
    def decorator(fn):
        JOB_HANDLERS[kind] = fn
        return fn

    return decorator


@register_handler("seed_catalog")
def handle_seed_catalog(payload: dict[str, Any]) -> tuple[dict[str, Any], None]:
    from compare_pipeline.catalog import seed_catalog

    res = seed_catalog()
    return res, None


@register_handler("discover")
def handle_discover(payload: dict[str, Any]) -> tuple[dict[str, Any], None]:
    from compare_pipeline.discovery.discovery import run_discovery

    res = run_discovery()
    return res, None


@register_handler("research")
def handle_research(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]:
    import uuid

    from compare_pipeline.research import run_competitor_research

    with get_pipeline_session() as session:
        comp_id = uuid.UUID(payload["competitor_id"])
        res = run_competitor_research(session, comp_id)
        return res, ("generate", {"competitor_id": str(comp_id)})


@register_handler("generate")
def handle_generate(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]:
    import uuid

    from compare_pipeline.generation import generate_comparison_draft

    with get_pipeline_session() as session:
        comp_id = uuid.UUID(payload["competitor_id"])
        res = generate_comparison_draft(session, comp_id)
        return res, ("gate", {"article_id": res["article_id"]})


@register_handler("gate")
def handle_gate(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]:
    import uuid

    from compare_pipeline.gate import run_article_gate
    from compare_pipeline.models import Article, ArticleVersion
    from compare_pipeline.models_article import ArticleDraft

    with get_pipeline_session() as session:
        art_id = uuid.UUID(payload["article_id"])
        article = session.query(Article).filter(Article.id == art_id).one()
        version = (
            session.query(ArticleVersion)
            .filter(ArticleVersion.id == article.current_version_id)
            .one()
        )
        draft = ArticleDraft.model_validate(version.content)
        report = run_article_gate(
            draft, session=session, competitor_id=article.competitor_id
        )
        version.gate_report = report.to_dict()
        version.gate_stale = False
        if report.passed:
            article.status = "needs_review"
        else:
            article.status = "needs_attention"
        session.commit()
        return report.to_dict(), None


@register_handler("push_webflow")
def handle_push_webflow(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], None]:
    import uuid

    from compare_pipeline.models import Article, ArticleVersion
    from compare_pipeline.webflow import WebflowSafeClient

    with get_pipeline_session() as session:
        art_id = uuid.UUID(payload["article_id"])
        article = session.query(Article).filter(Article.id == art_id).one()
        version = (
            session.query(ArticleVersion)
            .filter(ArticleVersion.id == article.current_version_id)
            .one()
        )
        client = WebflowSafeClient()
        fields = {
            "name": version.content.get("title"),
            "slug": article.slug,
            "body": version.webflow_html,
        }
        res = client.push_draft_item(client.collection_id or "test_col", fields)
        article.webflow_item_id = res.get("id")
        session.commit()
        return res, None


class Worker:
    def __init__(
        self,
        poll_interval: float = 2.0,
        reaper_interval: float = 60.0,
        heartbeat_interval: float = 5.0,
    ):
        self.poll_interval = poll_interval
        self.reaper_interval = reaper_interval
        self.heartbeat_interval = heartbeat_interval
        self.running = True
        self.last_reap = 0.0

    def stop(self, *args):
        logger.info("Worker stop requested, shutting down gracefully...")
        self.running = False

    def run_once(self) -> bool:
        """Processes one job if available. Returns True if a job was processed."""
        # Check reaper
        now = time.time()
        if now - self.last_reap > self.reaper_interval:
            with get_pipeline_session() as session:
                reaped = reap_stale_jobs(session)
                if reaped:
                    logger.warning("Reaped %d stale jobs", reaped)
            self.last_reap = now

        # Claim a job
        with get_pipeline_session() as session:
            job = claim_job(session)
            if not job:
                return False

            job_id = job.id
            kind = job.kind
            payload = dict(job.payload or {})
            logger.info("Claimed job %s [%s] (attempt %d)", job_id, kind, job.attempts)

        # Execute handler outside the claiming session
        handler = JOB_HANDLERS.get(kind)
        if not handler:
            err = f"No handler registered for job kind '{kind}'"
            logger.error(err)
            with get_pipeline_session() as session:
                fail_job(session, job_id, err)
            return True

        import threading
        from sqlalchemy import text

        stop_hb = threading.Event()

        def _heartbeat():
            while not stop_hb.wait(self.heartbeat_interval):
                try:
                    with get_pipeline_session() as hb_session:
                        hb_session.execute(
                            text(
                                "UPDATE app.jobs SET heartbeat_at = clock_timestamp() WHERE id = :jid AND status = 'running'"
                            ),
                            {"jid": job_id},
                        )
                        hb_session.commit()
                except Exception as exc:
                    logger.debug("Heartbeat ping skipped: %s", exc)

        hb_thread = threading.Thread(target=_heartbeat, daemon=True)
        hb_thread.start()

        try:
            result, chain_next = handler(payload)
            with get_pipeline_session() as session:
                chained_id = complete_job(
                    session, job_id, result=result, chain_next=chain_next
                )
                logger.info(
                    "Job %s completed successfully. Chained: %s", job_id, chained_id
                )
        except Exception as e:
            logger.exception("Job %s failed with error: %s", job_id, e)
            with get_pipeline_session() as session:
                retried = fail_job(session, job_id, str(e))
                if retried:
                    logger.info("Job %s re-queued with exponential backoff", job_id)
                else:
                    logger.error("Job %s failed permanently", job_id)
        finally:
            stop_hb.set()
            hb_thread.join(timeout=1.0)

        return True

    def start(self):
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        logger.info("Worker started, waiting for jobs...")

        while self.running:
            processed = self.run_once()
            if not processed:
                time.sleep(self.poll_interval)


if __name__ == "__main__":
    worker = Worker()
    worker.start()
