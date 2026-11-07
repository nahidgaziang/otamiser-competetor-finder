"""Database roles, triggers and the job-request function (V9; guide section 7)."""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest


def _article(
    superuser: psycopg.Connection, comp_id: uuid.UUID, status: str = "draft"
) -> uuid.UUID:
    row = superuser.execute(
        "INSERT INTO app.articles (competitor_id, slug, status) VALUES (%s, %s, %s) RETURNING id",
        (comp_id, f"otamiser-vs-review-{uuid.uuid4().hex[:8]}", status),
    ).fetchone()
    assert row is not None
    return row[0]


# --- publishing lock ------------------------------------------------------------------------------


def test_pipeline_cannot_insert_an_already_published_article(
    as_pipeline: psycopg.Connection, competitor: uuid.UUID
) -> None:
    with pytest.raises(
        psycopg.errors.RaiseException, match="forbidden from publishing"
    ):
        as_pipeline.execute(
            "INSERT INTO app.articles (competitor_id, slug, status) VALUES (%s, %s, 'published')",
            (competitor, f"otamiser-vs-sneaky-{uuid.uuid4().hex[:6]}"),
        )


def test_pipeline_cannot_set_hub_published_at(
    as_pipeline: psycopg.Connection,
    superuser: psycopg.Connection,
    competitor: uuid.UUID,
) -> None:
    art = _article(superuser, competitor)
    with pytest.raises(psycopg.errors.RaiseException):
        as_pipeline.execute(
            "UPDATE app.articles SET hub_published_at = now() WHERE id = %s", (art,)
        )


def test_pipeline_can_still_update_draft_fields(
    as_pipeline: psycopg.Connection,
    superuser: psycopg.Connection,
    competitor: uuid.UUID,
) -> None:
    art = _article(superuser, competitor)
    as_pipeline.execute(
        "UPDATE app.articles SET status = 'needs_review' WHERE id = %s", (art,)
    )
    row = superuser.execute(
        "SELECT status FROM app.articles WHERE id = %s", (art,)
    ).fetchone()
    assert row == ("needs_review",)


def test_pipeline_cannot_unpublish_by_editing_published_by(
    as_pipeline: psycopg.Connection,
    superuser: psycopg.Connection,
    competitor: uuid.UUID,
) -> None:
    art = _article(superuser, competitor)
    superuser.execute(
        "UPDATE app.articles SET status='published', hub_published_at=now(), hub_published_by='human' WHERE id=%s",
        (art,),
    )
    with pytest.raises(psycopg.errors.RaiseException):
        as_pipeline.execute(
            "UPDATE app.articles SET hub_published_by = NULL WHERE id = %s", (art,)
        )


def test_published_view_only_exposes_published_articles(
    superuser: psycopg.Connection, competitor: uuid.UUID
) -> None:
    draft = _article(superuser, competitor, "needs_attention")
    rows = superuser.execute(
        "SELECT 1 FROM app.published_articles WHERE article_id = %s", (draft,)
    ).fetchall()
    assert rows == []


# --- least privilege ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table", ["competitors", "articles", "jobs", "claims", "admin_audit_log"]
)
def test_pipeline_cannot_delete(as_pipeline: psycopg.Connection, table: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_pipeline.execute(f"DELETE FROM app.{table} WHERE false")  # noqa: S608 - fixed table names


@pytest.mark.parametrize(
    "table", ["competitors", "articles", "jobs", "admin_audit_log", "llm_calls"]
)
def test_web_cannot_delete(as_web: psycopg.Connection, table: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_web.execute(f"DELETE FROM app.{table} WHERE false")  # noqa: S608


def test_web_cannot_modify_jobs_directly(as_web: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_web.execute("UPDATE app.jobs SET status = 'queued' WHERE false")


def test_web_cannot_rewrite_the_audit_log(as_web: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_web.execute(
            "UPDATE app.admin_audit_log SET actor = 'someone-else' WHERE false"
        )


def test_neither_role_can_change_schema(
    as_pipeline: psycopg.Connection, as_web: psycopg.Connection
) -> None:
    for conn in (as_pipeline, as_web):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("ALTER TABLE app.articles ADD COLUMN x int")


def test_pipeline_cannot_rewrite_the_audit_log(as_pipeline: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_pipeline.execute("UPDATE app.admin_audit_log SET actor = 'x' WHERE false")


def test_pipeline_cannot_forge_admin_audit_entries(
    as_pipeline: psycopg.Connection,
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_pipeline.execute(
            "INSERT INTO app.admin_audit_log (action, entity_type, actor) VALUES ('publish_article','article','human_admin')"
        )


def test_pipeline_cannot_touch_migration_state(as_pipeline: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_pipeline.execute(
            "UPDATE app.alembic_version SET version_num = version_num WHERE false"
        )


def test_request_job_is_not_executable_by_public(superuser: psycopg.Connection) -> None:
    row = superuser.execute(
        """
        SELECT coalesce(bool_or(a.grantee = 0 AND a.privilege_type = 'EXECUTE'), p.proacl IS NULL)
        FROM pg_proc p
        LEFT JOIN LATERAL aclexplode(p.proacl) a ON true
        WHERE p.proname = 'request_job'
        GROUP BY p.proacl
        """
    ).fetchone()
    assert row is not None and row[0] is False


def test_hub_has_a_read_only_role(superuser: psycopg.Connection) -> None:
    roles = {r[0] for r in superuser.execute("SELECT rolname FROM pg_roles").fetchall()}
    assert roles & {"hub_ro", "web_hub_ro", "hub_read"}


# --- request_job validation -----------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["drop_tables", "publish", "", "DISCOVER"])
def test_request_job_rejects_unknown_kinds(
    as_web: psycopg.Connection, kind: str
) -> None:
    with pytest.raises(psycopg.errors.RaiseException, match="Invalid job kind"):
        as_web.execute(
            "SELECT app.request_job(%s, '{}'::jsonb, 'review_test')", (kind,)
        )


def test_request_job_requires_ids(as_web: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.RaiseException, match="competitor_id"):
        as_web.execute("SELECT app.request_job('research', '{}'::jsonb, 'review_test')")
    with pytest.raises(psycopg.errors.RaiseException, match="article_id"):
        as_web.execute(
            "SELECT app.request_job('push_webflow', '{}'::jsonb, 'review_test')"
        )


def test_request_job_dedupes_active_jobs(
    as_web: psycopg.Connection, competitor: uuid.UUID
) -> None:
    payload = json.dumps({"competitor_id": str(competitor)})
    a = as_web.execute(
        "SELECT app.request_job('research', %s::jsonb, 'review_test')", (payload,)
    ).fetchone()
    b = as_web.execute(
        "SELECT app.request_job('research', %s::jsonb, 'review_test')", (payload,)
    ).fetchone()
    assert a == b


@pytest.mark.parametrize("bad_id", ["not-a-uuid", str(uuid.UUID(int=0))])
def test_request_job_validates_competitor_id(
    as_web: psycopg.Connection, bad_id: str
) -> None:
    with pytest.raises(psycopg.Error):
        as_web.execute(
            "SELECT app.request_job('research', %s::jsonb, 'review_test')",
            (json.dumps({"competitor_id": bad_id}),),
        )


def test_caller_cannot_choose_dedupe_key(
    as_web: psycopg.Connection, competitor: uuid.UUID
) -> None:
    ids = {
        as_web.execute(
            "SELECT app.request_job('research', %s::jsonb, 'review_test')",
            (json.dumps({"competitor_id": str(competitor), "dedupe_key": f"k{i}"}),),
        ).fetchone()
        for i in range(2)
    }
    assert len(ids) == 1
