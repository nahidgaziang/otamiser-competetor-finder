# Competitor Intelligence Processing Pipeline

Automated competitor discovery, evidence-backed research, comparison-article generation, and quality gate system.

## Architecture & Database (PostgreSQL 18)

Schema: `app`

### Roles & Security Safeguards
1. **`migrator`**: Owns schema `app`, executes Alembic migrations.
2. **`pipeline_rw`**: The worker execution role.
   - `SELECT, INSERT, UPDATE` on all tables in `app`.
   - **`REVOKE DELETE`**: Permanently blocked from deleting records.
   - **Zero Automatic Publishing Trigger**: A database trigger on `app.articles` explicitly checks `current_user` and raises an exception if `pipeline_rw` attempts to set `status = 'published'` or modify `hub_published_*` columns.
3. **`web_app`**: Web UI role.
   - Reads all data.
   - Reviews and updates drafts, claims, and competitors.
   - Direct `INSERT`, `UPDATE`, `DELETE` on `app.jobs` is revoked.
   - Must request jobs through the `SECURITY DEFINER` function `app.request_job(...)`.

### Job Queue System
- Backed by `app.jobs` with partial unique index on `dedupe_key WHERE status IN ('queued', 'running')`.
- Worker claiming uses `FOR UPDATE SKIP LOCKED`.
- Exponential backoff retry mechanism with heartbeat reporting.
- Reaper identifies abandoned/timed-out tasks and re-queues them.
- Autonomous job chaining: `research → generate → gate`.

## Running Tests

```bash
uv run pytest -v
```

