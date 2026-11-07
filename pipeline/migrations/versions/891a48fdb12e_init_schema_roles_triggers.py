"""init_schema_roles_triggers

Revision ID: 891a48fdb12e
Revises:
Create Date: 2026-11-07 16:40:10.228017

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "891a48fdb12e"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Competitors
    op.create_table(
        "competitors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("canonical_domain", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("segment", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column(
            "is_partner", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'candidate'")
        ),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("canonical_domain", name="uq_competitors_canonical_domain"),
        schema="app",
    )

    # 2. Discovery Hits
    op.create_table(
        "discovery_hits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column(
            "raw_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # 3. Source Snapshots
    op.create_table(
        "source_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "competitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.competitors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_tier", sa.Text(), nullable=False),
        sa.Column("fetcher", sa.Text(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # 4. Claims
    op.create_table(
        "claims",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "competitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.competitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.source_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'verified'")
        ),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # 5. Articles (without current_version_id FK initially to resolve circular dependency)
    op.create_table(
        "articles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "competitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.competitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column("hub_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hub_published_by", sa.Text(), nullable=True),
        sa.Column("webflow_item_id", sa.Text(), nullable=True),
        sa.Column("webflow_last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name="uq_articles_slug"),
        schema="app",
    )

    # 6. Article Versions
    op.create_table(
        "article_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("webflow_html", sa.Text(), nullable=False),
        sa.Column(
            "gate_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "gate_stale", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "source", sa.Text(), nullable=False, server_default=sa.text("'ai_pipeline'")
        ),
        sa.Column("editor", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # Add FK from articles.current_version_id to article_versions.id
    op.create_foreign_key(
        "fk_articles_current_version",
        "articles",
        "article_versions",
        ["current_version_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="SET NULL",
        deferrable=True,
        initially="DEFERRED",
    )

    # 7. Jobs
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'queued'")
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")
        ),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "trigger", sa.Text(), nullable=False, server_default=sa.text("'manual'")
        ),
        sa.Column(
            "requested_by",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    op.create_index(
        "idx_jobs_active_dedupe",
        "jobs",
        ["dedupe_key"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "idx_jobs_claim",
        "jobs",
        ["status", "run_after"],
        schema="app",
        postgresql_where=sa.text("status = 'queued'"),
    )

    # 8. LLM Calls
    op.create_table(
        "llm_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_preview", sa.Text(), nullable=True),
        sa.Column("response_preview", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # 9. Admin Audit Log
    op.create_table(
        "admin_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # 10. Settings
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # 11. Metrics
    op.create_table(
        "metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("goal_id", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Numeric(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )

    # 12. View: app.published_articles
    op.execute("""
    CREATE OR REPLACE VIEW app.published_articles AS
    SELECT 
        a.id AS article_id,
        a.slug,
        a.hub_published_at,
        a.hub_published_by,
        c.id AS competitor_id,
        c.name AS competitor_name,
        c.canonical_domain,
        c.summary AS competitor_summary,
        v.id AS version_id,
        v.version_number,
        v.content,
        v.webflow_html,
        v.created_at AS version_created_at
    FROM app.articles a
    JOIN app.competitors c ON a.competitor_id = c.id
    JOIN app.article_versions v ON a.current_version_id = v.id
    WHERE a.status = 'published';
    """)

    # 13. Trigger to prevent pipeline_rw from publishing or updating hub_published columns
    op.execute("""
    CREATE OR REPLACE FUNCTION app.check_article_publish_permission()
    RETURNS TRIGGER AS $$
    BEGIN
        IF (NEW.status = 'published' AND (OLD.status IS NULL OR OLD.status IS DISTINCT FROM 'published'))
           OR (NEW.hub_published_at IS DISTINCT FROM OLD.hub_published_at)
           OR (NEW.hub_published_by IS DISTINCT FROM OLD.hub_published_by) THEN
            IF current_user = 'pipeline_rw' THEN
                RAISE EXCEPTION 'Permission denied: pipeline_rw is forbidden from publishing articles or updating hub_published columns.';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_check_article_publish
    BEFORE UPDATE OR INSERT ON app.articles
    FOR EACH ROW
    EXECUTE FUNCTION app.check_article_publish_permission();
    """)

    # 14. Stored procedure: app.request_job
    op.execute("""
    CREATE OR REPLACE FUNCTION app.request_job(
        p_kind text,
        p_payload jsonb DEFAULT '{}'::jsonb,
        p_requested_by text DEFAULT 'system'
    )
    RETURNS uuid
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = app, pg_catalog
    AS $$
    DECLARE
        v_job_id uuid;
        v_dedupe_key text := NULL;
    BEGIN
        -- Validate allowed kinds
        IF p_kind NOT IN ('discover', 'research', 'generate', 'gate', 'push_webflow', 'seed_catalog') THEN
            RAISE EXCEPTION 'Invalid job kind: %', p_kind;
        END IF;

        IF p_payload IS NULL THEN
            p_payload := '{}'::jsonb;
        END IF;

        -- Validate required payload fields
        IF p_kind IN ('research', 'generate') AND NOT (p_payload ? 'competitor_id') THEN
            RAISE EXCEPTION 'Job kind % requires competitor_id in payload', p_kind;
        END IF;

        IF p_kind IN ('gate', 'push_webflow') AND NOT (p_payload ? 'article_id') THEN
            RAISE EXCEPTION 'Job kind % requires article_id in payload', p_kind;
        END IF;

        -- Derive dedupe_key if not provided
        IF p_payload ? 'dedupe_key' THEN
            v_dedupe_key := p_payload->>'dedupe_key';
        ELSE
            IF p_kind = 'seed_catalog' THEN
                v_dedupe_key := 'seed_catalog';
            ELSIF p_kind = 'discover' THEN
                v_dedupe_key := 'discover_' || to_char(now(), 'YYYYMMDD_HH24');
            ELSIF p_kind IN ('research', 'generate') THEN
                v_dedupe_key := p_kind || '_' || (p_payload->>'competitor_id');
            ELSIF p_kind IN ('gate', 'push_webflow') THEN
                v_dedupe_key := p_kind || '_' || (p_payload->>'article_id');
            END IF;
        END IF;

        -- Insert job with partial unique constraint handling
        INSERT INTO app.jobs (kind, payload, dedupe_key, status, requested_by)
        VALUES (p_kind, p_payload, v_dedupe_key, 'queued', p_requested_by)
        ON CONFLICT (dedupe_key) WHERE status IN ('queued', 'running')
        DO UPDATE SET updated_at = now()
        RETURNING id INTO v_job_id;

        IF v_job_id IS NULL AND v_dedupe_key IS NOT NULL THEN
            SELECT id INTO v_job_id FROM app.jobs
            WHERE dedupe_key = v_dedupe_key AND status IN ('queued', 'running')
            LIMIT 1;
        END IF;

        PERFORM pg_notify('jobs', json_build_object('job_id', v_job_id, 'kind', p_kind)::text);

        RETURN v_job_id;
    END;
    $$;
    """)

    # 15. Role Grants & Restrictions
    op.execute("""
    -- Grants for pipeline_rw (worker)
    GRANT USAGE ON SCHEMA app TO pipeline_rw;
    GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA app TO pipeline_rw;
    REVOKE DELETE ON ALL TABLES IN SCHEMA app FROM pipeline_rw;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO pipeline_rw;
    GRANT EXECUTE ON FUNCTION app.request_job(text, jsonb, text) TO pipeline_rw;

    -- Grants for web_app (admin UI & hub)
    GRANT USAGE ON SCHEMA app TO web_app;
    GRANT SELECT ON ALL TABLES IN SCHEMA app TO web_app;
    GRANT UPDATE ON app.competitors, app.claims, app.articles, app.article_versions, app.settings TO web_app;
    GRANT INSERT ON app.articles, app.article_versions, app.admin_audit_log TO web_app;
    -- Strictly forbid direct job mutations; jobs created ONLY via app.request_job()
    REVOKE INSERT, UPDATE, DELETE ON app.jobs FROM web_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO web_app;
    GRANT EXECUTE ON FUNCTION app.request_job(text, jsonb, text) TO web_app;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_check_article_publish ON app.articles;")
    op.execute("DROP FUNCTION IF EXISTS app.check_article_publish_permission();")
    op.execute("DROP FUNCTION IF EXISTS app.request_job(text, jsonb, text);")
    op.execute("DROP VIEW IF EXISTS app.published_articles;")
    op.drop_table("metrics", schema="app")
    op.drop_table("settings", schema="app")
    op.drop_table("admin_audit_log", schema="app")
    op.drop_table("llm_calls", schema="app")
    op.drop_table("jobs", schema="app")
    op.drop_constraint(
        "fk_articles_current_version", "articles", schema="app", type_="foreignkey"
    )
    op.drop_table("article_versions", schema="app")
    op.drop_table("articles", schema="app")
    op.drop_table("claims", schema="app")
    op.drop_table("source_snapshots", schema="app")
    op.drop_table("discovery_hits", schema="app")
    op.drop_table("competitors", schema="app")
