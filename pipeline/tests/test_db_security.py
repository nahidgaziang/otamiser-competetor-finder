import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from compare_pipeline.db import get_admin_session, get_pipeline_session, get_web_session


def test_pipeline_rw_cannot_delete():
    """Validates that pipeline_rw is strictly forbidden from deleting rows (REVOKE DELETE)."""
    unique_domain = f"del-test-{uuid.uuid4().hex[:8]}.com"

    # Insert a competitor with pipeline_rw
    with get_pipeline_session() as session:
        session.execute(
            text(
                """
                INSERT INTO app.competitors (name, canonical_domain, status)
                VALUES ('Delete Test Competitor', :domain, 'candidate');
                """
            ),
            {"domain": unique_domain},
        )

    # Attempt to delete with pipeline_rw - MUST fail with permission denied
    with pytest.raises(DBAPIError) as exc_info, get_pipeline_session() as session:
        session.execute(
            text(
                """
                    DELETE FROM app.competitors WHERE canonical_domain = :domain;
                    """
            ),
            {"domain": unique_domain},
        )

    assert "permission denied" in str(exc_info.value).lower()

    # Cleanup with admin
    with get_admin_session() as session:
        session.execute(
            text("DELETE FROM app.competitors WHERE canonical_domain = :domain;"),
            {"domain": unique_domain},
        )


def test_pipeline_rw_cannot_publish_article():
    """Validates that the database trigger blocks pipeline_rw from setting articles.status='published'."""
    unique_domain = f"pub-test-{uuid.uuid4().hex[:8]}.com"
    unique_slug = f"test-slug-{uuid.uuid4().hex[:8]}"

    # Insert competitor & draft article as pipeline_rw
    with get_pipeline_session() as session:
        comp_id = session.execute(
            text(
                """
                INSERT INTO app.competitors (name, canonical_domain, status)
                VALUES ('Publish Test Competitor', :domain, 'candidate')
                RETURNING id;
                """
            ),
            {"domain": unique_domain},
        ).scalar_one()

        article_id = session.execute(
            text(
                """
                INSERT INTO app.articles (competitor_id, slug, status)
                VALUES (:comp_id, :slug, 'draft')
                RETURNING id;
                """
            ),
            {"comp_id": comp_id, "slug": unique_slug},
        ).scalar_one()

    # Attempt to publish as pipeline_rw - MUST be blocked by trigger
    with pytest.raises(DBAPIError) as exc_info, get_pipeline_session() as session:
        session.execute(
            text(
                """
                    UPDATE app.articles
                    SET status = 'published'
                    WHERE id = :article_id;
                    """
            ),
            {"article_id": article_id},
        )

    assert "forbidden from publishing" in str(exc_info.value)

    # Attempt to modify hub_published_by as pipeline_rw - MUST also be blocked by trigger
    with pytest.raises(DBAPIError) as exc_info2, get_pipeline_session() as session:
        session.execute(
            text(
                """
                    UPDATE app.articles
                    SET hub_published_by = 'rogue_ai'
                    WHERE id = :article_id;
                    """
            ),
            {"article_id": article_id},
        )

    assert "forbidden from publishing" in str(exc_info2.value)

    # Cleanup with admin
    with get_admin_session() as session:
        session.execute(
            text("DELETE FROM app.competitors WHERE id = :comp_id;"),
            {"comp_id": comp_id},
        )


def test_web_app_cannot_insert_jobs_directly():
    """Validates that web_app role cannot directly INSERT into app.jobs."""
    with pytest.raises(DBAPIError) as exc_info, get_web_session() as session:
        session.execute(
            text(
                """
                    INSERT INTO app.jobs (kind, payload, status)
                    VALUES ('discover', '{}'::jsonb, 'queued');
                    """
            )
        )

    assert "permission denied" in str(exc_info.value).lower()


def test_web_app_can_request_jobs_via_stored_proc():
    """Validates that web_app CAN enqueue jobs through the SECURITY DEFINER app.request_job() procedure."""
    with get_web_session() as session:
        job_id = session.execute(
            text(
                """
                SELECT app.request_job('seed_catalog', '{}'::jsonb, 'admin_user');
                """
            )
        ).scalar_one()
        assert job_id is not None

    # Cleanup with admin
    with get_admin_session() as session:
        session.execute(
            text("DELETE FROM app.jobs WHERE id = :job_id;"),
            {"job_id": job_id},
        )


def test_web_app_can_publish_article():
    """Validates that web_app (human admin in UI) CAN publish articles."""
    unique_domain = f"admin-pub-{uuid.uuid4().hex[:8]}.com"
    unique_slug = f"admin-slug-{uuid.uuid4().hex[:8]}"

    with get_admin_session() as session:
        comp_id = session.execute(
            text(
                """
                INSERT INTO app.competitors (name, canonical_domain, status)
                VALUES ('Admin Pub Competitor', :domain, 'candidate')
                RETURNING id;
                """
            ),
            {"domain": unique_domain},
        ).scalar_one()

        article_id = session.execute(
            text(
                """
                INSERT INTO app.articles (competitor_id, slug, status)
                VALUES (:comp_id, :slug, 'draft')
                RETURNING id;
                """
            ),
            {"comp_id": comp_id, "slug": unique_slug},
        ).scalar_one()

    # Publish with web_app role
    with get_web_session() as session:
        session.execute(
            text(
                """
                UPDATE app.articles
                SET status = 'published',
                    hub_published_at = now(),
                    hub_published_by = 'human_admin'
                WHERE id = :article_id;
                """
            ),
            {"article_id": article_id},
        )

        res = session.execute(
            text("SELECT status, hub_published_by FROM app.articles WHERE id = :id;"),
            {"id": article_id},
        ).fetchone()
        assert res[0] == "published"
        assert res[1] == "human_admin"

    # Cleanup with admin
    with get_admin_session() as session:
        session.execute(
            text("DELETE FROM app.competitors WHERE id = :comp_id;"),
            {"comp_id": comp_id},
        )
