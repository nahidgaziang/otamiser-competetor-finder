import uuid

import pytest
from sqlalchemy import text

from compare_pipeline.db import get_admin_session, get_pipeline_session
from compare_pipeline.jobs import (
    claim_job,
    complete_job,
    fail_job,
    heartbeat_job,
    reap_stale_jobs,
    request_job,
)
from compare_pipeline.models import Job


def test_job_validation():
    """Validates that app.request_job() rejects invalid kinds or missing payloads."""
    # Invalid job kind
    with get_pipeline_session() as session:
        with pytest.raises(Exception) as exc_info:
            request_job(session, kind="illegal_kind")
        assert "Invalid job kind" in str(exc_info.value)

    # Missing competitor_id for research
    with get_pipeline_session() as session:
        with pytest.raises(Exception) as exc_info:
            request_job(session, kind="research", payload={})
        assert "requires competitor_id" in str(exc_info.value)

    # Missing article_id for gate
    with get_pipeline_session() as session:
        with pytest.raises(Exception) as exc_info:
            request_job(session, kind="gate", payload={})
        assert "requires article_id" in str(exc_info.value)


def test_job_deduplication():
    """Validates dedupe_key partial unique index prevents duplicate active jobs."""
    test_comp_id = str(uuid.uuid4())
    dedupe_val = f"research_{test_comp_id}"

    with get_pipeline_session() as session:
        # First request
        job_id_1 = request_job(
            session,
            kind="research",
            payload={"competitor_id": test_comp_id, "dedupe_key": dedupe_val},
        )
        assert job_id_1 is not None

        # Second request with same dedupe_key while queued
        job_id_2 = request_job(
            session,
            kind="research",
            payload={"competitor_id": test_comp_id, "dedupe_key": dedupe_val},
        )
        # Should return the same active job ID without creating a duplicate
        assert job_id_1 == job_id_2

        # Check only 1 row exists
        count = session.execute(
            text("SELECT count(*) FROM app.jobs WHERE dedupe_key = :dk;"),
            {"dk": dedupe_val},
        ).scalar_one()
        assert count == 1

    # Cleanup
    with get_admin_session() as session:
        session.execute(
            text("DELETE FROM app.jobs WHERE dedupe_key = :dk;"), {"dk": dedupe_val}
        )


def test_job_claim_skip_locked():
    """Validates claiming via FOR UPDATE SKIP LOCKED across concurrent worker sessions."""
    # Seed 2 queued jobs
    with get_pipeline_session() as session:
        j1 = request_job(
            session,
            kind="seed_catalog",
            payload={"dedupe_key": f"test_claim_{uuid.uuid4().hex[:6]}"},
        )
        j2 = request_job(
            session,
            kind="seed_catalog",
            payload={"dedupe_key": f"test_claim_{uuid.uuid4().hex[:6]}"},
        )

    # Worker session 1 claims first job
    with get_pipeline_session() as s1:
        claimed1 = claim_job(s1)
        assert claimed1 is not None
        assert claimed1.status == "running"
        assert claimed1.attempts == 1

        # Worker session 2 claims next job concurrently without blocking or picking job 1
        with get_pipeline_session() as s2:
            claimed2 = claim_job(s2)
            assert claimed2 is not None
            assert claimed2.status == "running"
            assert claimed1.id != claimed2.id

        # Worker session 3 finds no more jobs
        with get_pipeline_session() as s3:
            claimed3 = claim_job(s3)
            assert claimed3 is None

    # Cleanup
    with get_admin_session() as session:
        session.execute(
            text("DELETE FROM app.jobs WHERE id IN (:j1, :j2);"), {"j1": j1, "j2": j2}
        )


def test_job_heartbeat():
    """Validates that heartbeat updates heartbeat_at for running jobs."""
    with get_pipeline_session() as session:
        j_id = request_job(
            session,
            kind="seed_catalog",
            payload={"dedupe_key": f"hb_{uuid.uuid4().hex[:6]}"},
        )
        job = claim_job(session)
        assert job is not None
        initial_hb = job.heartbeat_at

        hb_res = heartbeat_job(session, j_id)
        assert hb_res is True

        refreshed = session.query(Job).filter(Job.id == j_id).one()
        assert refreshed.heartbeat_at >= initial_hb

    # Cleanup
    with get_admin_session() as session:
        session.execute(text("DELETE FROM app.jobs WHERE id = :id;"), {"id": j_id})


def test_job_retry_backoff_and_terminal_failure():
    """Validates retry with exponential backoff on failure, and failure after max_attempts."""
    with get_pipeline_session() as session:
        j_id = request_job(
            session,
            kind="seed_catalog",
            payload={"dedupe_key": f"retry_{uuid.uuid4().hex[:6]}"},
        )

        # Attempt 1
        job = claim_job(session)
        assert job.attempts == 1
        retried = fail_job(session, j_id, "Network timeout")
        assert retried is True

        # Check job is queued with future run_after
        refreshed = session.query(Job).filter(Job.id == j_id).one()
        assert refreshed.status == "queued"
        assert refreshed.error == "Network timeout"

        # Force run_after to past to simulate time passed
        session.execute(
            text(
                "UPDATE app.jobs SET run_after = now() - interval '1 second' WHERE id = :id"
            ),
            {"id": j_id},
        )
        session.commit()

        # Attempt 2
        job = claim_job(session)
        assert job.attempts == 2
        fail_job(session, j_id, "Network timeout 2")
        session.execute(
            text(
                "UPDATE app.jobs SET run_after = now() - interval '1 second' WHERE id = :id"
            ),
            {"id": j_id},
        )
        session.commit()

        # Attempt 3 (reaches max_attempts = 3)
        job = claim_job(session)
        assert job.attempts == 3
        retried_final = fail_job(session, j_id, "Terminal fatal error")
        assert retried_final is False  # terminal failure

        term_job = session.query(Job).filter(Job.id == j_id).one()
        assert term_job.status == "failed"
        assert term_job.error == "Terminal fatal error"

    # Cleanup
    with get_admin_session() as session:
        session.execute(text("DELETE FROM app.jobs WHERE id = :id;"), {"id": j_id})


def test_job_reaper():
    """Validates that reap_stale_jobs identifies abandoned jobs and resets them."""
    with get_pipeline_session() as session:
        j_id = request_job(
            session,
            kind="seed_catalog",
            payload={"dedupe_key": f"reap_{uuid.uuid4().hex[:6]}"},
        )
        claim_job(session)

        # Force heartbeat into past (> 300s ago)
        session.execute(
            text(
                """
                UPDATE app.jobs 
                SET heartbeat_at = now() - interval '10 minutes'
                WHERE id = :id;
                """
            ),
            {"id": j_id},
        )
        session.commit()

        # Run reaper
        reaped_count = reap_stale_jobs(session, timeout_seconds=300)
        assert reaped_count >= 1

        reaped_job = session.query(Job).filter(Job.id == j_id).one()
        assert reaped_job.status == "queued"
        assert "reaper" in reaped_job.error

    # Cleanup
    with get_admin_session() as session:
        session.execute(text("DELETE FROM app.jobs WHERE id = :id;"), {"id": j_id})


def test_job_chaining():
    """Validates chaining jobs: research completion enqueues generate, which enqueues gate."""
    test_comp_id = str(uuid.uuid4())
    test_article_id = str(uuid.uuid4())

    with get_pipeline_session() as session:
        # Start research job
        res_id = request_job(
            session,
            kind="research",
            payload={
                "competitor_id": test_comp_id,
                "dedupe_key": f"chain_res_{test_comp_id}",
            },
        )
        job = claim_job(session)
        assert job.id == res_id

        # Complete research and chain generate
        gen_id = complete_job(
            session=session,
            job_id=res_id,
            result={"claims_count": 12},
            chain_next=(
                "generate",
                {
                    "competitor_id": test_comp_id,
                    "dedupe_key": f"chain_gen_{test_comp_id}",
                },
            ),
        )
        assert gen_id is not None

        # Verify generate job is queued
        gen_job = session.query(Job).filter(Job.id == gen_id).one()
        assert gen_job.kind == "generate"
        assert gen_job.status == "queued"
        assert gen_job.requested_by == "chain"

        # Claim generate job
        claimed_gen = claim_job(session)
        assert claimed_gen.id == gen_id

        # Complete generate and chain gate
        gate_id = complete_job(
            session=session,
            job_id=gen_id,
            result={"draft_generated": True},
            chain_next=(
                "gate",
                {
                    "article_id": test_article_id,
                    "dedupe_key": f"chain_gate_{test_article_id}",
                },
            ),
        )
        assert gate_id is not None

        gate_job = session.query(Job).filter(Job.id == gate_id).one()
        assert gate_job.kind == "gate"
        assert gate_job.status == "queued"

    # Cleanup
    with get_admin_session() as session:
        session.execute(
            text("DELETE FROM app.jobs WHERE id IN (:j1, :j2, :j3);"),
            {"j1": res_id, "j2": gen_id, "j3": gate_id},
        )
