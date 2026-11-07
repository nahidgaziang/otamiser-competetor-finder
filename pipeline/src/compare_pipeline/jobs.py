import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from compare_pipeline.models import Job


def request_job(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    requested_by: str = "system",
) -> uuid.UUID:
    """Invokes app.request_job() SECURITY DEFINER stored function."""
    payload_json = json.dumps(payload or {})
    res = session.execute(
        text("SELECT app.request_job(:kind, CAST(:payload AS jsonb), :requested_by)"),
        {"kind": kind, "payload": payload_json, "requested_by": requested_by},
    ).scalar_one()
    return uuid.UUID(str(res))


def claim_job(session: Session) -> Job | None:
    """Claims the next available queued job using FOR UPDATE SKIP LOCKED."""
    # Find candidate job ID locking the row
    row = session.execute(
        text(
            """
            SELECT id FROM app.jobs
            WHERE status = 'queued' AND run_after <= now()
            ORDER BY run_after ASC, created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1;
            """
        )
    ).fetchone()

    if not row:
        return None

    job_id = row[0]

    # Transition to running
    job = session.query(Job).filter(Job.id == job_id).one()
    job.status = "running"
    now_ts = datetime.now(UTC)
    job.locked_at = now_ts
    job.heartbeat_at = now_ts
    job.attempts += 1
    job.updated_at = now_ts
    session.flush()
    return job


def heartbeat_job(session: Session, job_id: uuid.UUID) -> bool:
    """Updates heartbeat timestamp for a running job."""
    res = session.execute(
        text(
            """
            UPDATE app.jobs
            SET heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id AND status = 'running';
            """
        ),
        {"job_id": job_id},
    )
    session.flush()
    return res.rowcount > 0


def complete_job(
    session: Session,
    job_id: uuid.UUID,
    result: dict[str, Any] | None = None,
    chain_next: tuple[str, dict[str, Any]] | None = None,
) -> uuid.UUID | None:
    """Marks a job completed and optionally chains the next job."""
    job = session.query(Job).filter(Job.id == job_id).one()
    job.status = "completed"
    job.result = result or {}
    job.locked_at = None
    job.updated_at = datetime.now(UTC)
    session.flush()

    chained_id = None
    if chain_next:
        next_kind, next_payload = chain_next
        chained_id = request_job(
            session=session,
            kind=next_kind,
            payload=next_payload,
            requested_by="chain",
        )
    return chained_id


def fail_job(session: Session, job_id: uuid.UUID, error_msg: str) -> bool:
    """Records job failure with backoff retry if attempts < max_attempts."""
    job = session.query(Job).filter(Job.id == job_id).one()
    job.error = error_msg
    job.locked_at = None
    now_ts = datetime.now(UTC)
    job.updated_at = now_ts

    if job.attempts < job.max_attempts:
        backoff_sec = (2**job.attempts) * 5
        job.status = "queued"
        job.run_after = now_ts + timedelta(seconds=backoff_sec)
        session.flush()
        return True  # Retried
    else:
        job.status = "failed"
        session.flush()
        return False  # Permanently failed


def reap_stale_jobs(session: Session, timeout_seconds: int = 300) -> int:
    """Requeues or fails abandoned/timed out running jobs."""
    res = session.execute(
        text(
            """
            UPDATE app.jobs
            SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                error = 'Job timed out / abandoned (reaper)',
                locked_at = NULL,
                updated_at = now()
            WHERE status = 'running' 
              AND heartbeat_at < now() - (interval '1 second' * :timeout);
            """
        ),
        {"timeout": timeout_seconds},
    )
    session.flush()
    return res.rowcount
