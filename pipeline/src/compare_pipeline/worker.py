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


class Worker:
    def __init__(self, poll_interval: float = 2.0, reaper_interval: float = 60.0):
        self.poll_interval = poll_interval
        self.reaper_interval = reaper_interval
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

        try:
            # Periodically heartbeat while executing
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
