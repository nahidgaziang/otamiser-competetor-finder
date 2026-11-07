"""add retry_job stored function

Revision ID: a00e250cc0ef
Revises: 891a48fdb12e
Create Date: 2026-11-07 23:22:31.716156

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a00e250cc0ef'
down_revision: Union[str, Sequence[str], None] = '891a48fdb12e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.retry_job(p_job_id uuid, p_requested_by text DEFAULT 'admin_ui'::text)
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'app', 'pg_catalog'
        AS $$
        DECLARE
            v_kind text;
            v_updated boolean := false;
        BEGIN
            UPDATE app.jobs
            SET status = 'queued',
                attempts = 0,
                error = NULL,
                locked_at = NULL,
                heartbeat_at = NULL,
                run_after = now(),
                requested_by = p_requested_by,
                updated_at = now()
            WHERE id = p_job_id AND status = 'failed'
            RETURNING kind INTO v_kind;

            IF FOUND THEN
                v_updated := true;
                PERFORM pg_notify('jobs', json_build_object('job_id', p_job_id, 'kind', v_kind, 'retry', true)::text);
            END IF;

            RETURN v_updated;
        END;
        $$;

        REVOKE EXECUTE ON FUNCTION app.retry_job(uuid, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.retry_job(uuid, text) TO web_app;
        GRANT EXECUTE ON FUNCTION app.retry_job(uuid, text) TO pipeline_rw;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION IF EXISTS app.retry_job(uuid, text);")
