"""Worker, job lifecycle and pipeline handlers against the real test database."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import psycopg
import pytest
from helpers import make_draft

from compare_pipeline import catalog, generation, worker
from compare_pipeline.db import get_pipeline_session
from compare_pipeline.jobs import claim_job, request_job


def _version(
    superuser: psycopg.Connection,
    comp: uuid.UUID,
    gate_passed: bool,
    status: str = "needs_attention",
) -> uuid.UUID:
    art = superuser.execute(
        "INSERT INTO app.articles (competitor_id, slug, status) VALUES (%s, %s, %s) RETURNING id",
        (comp, f"otamiser-vs-review-{uuid.uuid4().hex[:8]}", status),
    ).fetchone()[0]  # type: ignore[index]
    ver = superuser.execute(
        "INSERT INTO app.article_versions (article_id, version_number, content, webflow_html, gate_report) "
        "VALUES (%s, 1, %s, '<p>x</p>', %s) RETURNING id",
        (
            art,
            make_draft().model_dump_json(),
            json.dumps({"all_passed": gate_passed, "checks": {}}),
        ),
    ).fetchone()[0]  # type: ignore[index]
    superuser.execute(
        "UPDATE app.articles SET current_version_id = %s WHERE id = %s", (ver, art)
    )
    return art


def test_worker_runs_a_job_and_marks_it_complete(
    monkeypatch: pytest.MonkeyPatch, superuser: psycopg.Connection
) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setitem(
        worker.JOB_HANDLERS,
        "seed_catalog",
        lambda p: (seen.append(p) or {"ok": True}, None),
    )
    superuser.execute("DELETE FROM app.jobs")
    with get_pipeline_session() as s:
        job_id = request_job(
            s, "seed_catalog", {"dedupe_key": f"w-{uuid.uuid4().hex}"}, "review_test"
        )
    assert worker.Worker(reaper_interval=3600).run_once() is True
    status, result = superuser.execute(
        "SELECT status, result FROM app.jobs WHERE id=%s", (job_id,)
    ).fetchone()  # type: ignore[misc]
    assert status in ("completed", "succeeded") and result == {"ok": True}
    assert len(seen) == 1


def test_failing_handler_is_retried_with_backoff(
    monkeypatch: pytest.MonkeyPatch, superuser: psycopg.Connection
) -> None:
    def boom(_: dict[str, Any]) -> Any:
        raise RuntimeError("upstream down")

    monkeypatch.setitem(worker.JOB_HANDLERS, "seed_catalog", boom)
    superuser.execute("DELETE FROM app.jobs")
    with get_pipeline_session() as s:
        job_id = request_job(
            s, "seed_catalog", {"dedupe_key": f"f-{uuid.uuid4().hex}"}, "review_test"
        )
    worker.Worker(reaper_interval=3600).run_once()
    status, err, delayed = superuser.execute(
        "SELECT status, error, run_after > now() FROM app.jobs WHERE id=%s", (job_id,)
    ).fetchone()  # type: ignore[misc]
    assert (status, delayed) == ("queued", True) and "upstream down" in err


def test_two_workers_never_claim_the_same_job(superuser: psycopg.Connection) -> None:
    superuser.execute("DELETE FROM app.jobs")
    with get_pipeline_session() as s:
        request_job(
            s, "seed_catalog", {"dedupe_key": f"c-{uuid.uuid4().hex}"}, "review_test"
        )
    with get_pipeline_session() as s1, get_pipeline_session() as s2:
        first = claim_job(s1)
        second = claim_job(s2)
        assert first is not None and second is None


def test_worker_heartbeats_while_a_long_job_runs(
    monkeypatch: pytest.MonkeyPatch, superuser: psycopg.Connection
) -> None:
    superuser.execute("DELETE FROM app.jobs")
    beats: list[Any] = []

    def slow(_: dict[str, Any]) -> tuple[dict[str, Any], None]:
        first = superuser.execute(
            "SELECT heartbeat_at FROM app.jobs WHERE status='running'"
        ).fetchone()
        time.sleep(2.5)
        last = superuser.execute(
            "SELECT heartbeat_at FROM app.jobs WHERE status='running'"
        ).fetchone()
        beats.extend([first, last])
        return {}, None

    monkeypatch.setitem(worker.JOB_HANDLERS, "seed_catalog", slow)
    with get_pipeline_session() as s:
        request_job(
            s, "seed_catalog", {"dedupe_key": f"h-{uuid.uuid4().hex}"}, "review_test"
        )
    w = worker.Worker(reaper_interval=3600, heartbeat_interval=1)  # type: ignore[call-arg]
    w.run_once()
    assert beats[1][0] > beats[0][0]


def test_push_webflow_refuses_articles_that_failed_the_gate(
    superuser: psycopg.Connection, competitor: uuid.UUID
) -> None:
    art = _version(superuser, competitor, gate_passed=False)
    with pytest.raises(Exception):  # noqa: B017
        worker.handle_push_webflow({"article_id": str(art)})
    row = superuser.execute(
        "SELECT webflow_item_id FROM app.articles WHERE id=%s", (art,)
    ).fetchone()
    assert row == (None,)


def test_gate_handler_never_publishes(
    superuser: psycopg.Connection, competitor: uuid.UUID
) -> None:
    art = _version(superuser, competitor, gate_passed=True, status="draft")
    worker.handle_gate({"article_id": str(art)})
    status = superuser.execute(
        "SELECT status FROM app.articles WHERE id=%s", (art,)
    ).fetchone()
    assert status is not None and status[0] != "published"


def test_generation_derives_slug_from_the_competitor(
    monkeypatch: pytest.MonkeyPatch, superuser: psycopg.Connection
) -> None:
    monkeypatch.setattr(
        generation.LLMClient, "generate_structured", lambda self, **kw: make_draft()
    )
    comps = []
    for _ in range(2):
        cid = superuser.execute(
            "INSERT INTO app.competitors (name, canonical_domain) VALUES ('Dup Slug Co', %s) RETURNING id",
            (f"dup-{uuid.uuid4().hex[:8]}.example",),
        ).fetchone()[0]  # type: ignore[index]
        comps.append(cid)
    try:
        slugs = set()
        for cid in comps:
            with get_pipeline_session() as s:
                slugs.add(generation.generate_comparison_draft(s, cid)["slug"])
        assert len(slugs) == 2
    finally:
        superuser.execute("DELETE FROM app.competitors WHERE id = ANY(%s)", (comps,))


# --- catalog seeding ------------------------------------------------------------------------------

HUB = """
<a href="/compare/otamiser-vs-wheelhouse">Otamiser Revenue Management vs Wheelhouse Dynamic Pricing</a>
<a href="/compare/pricing-tool-vs-in-house-vs-otamiser">Pricing tools vs in-house revenue management teams vs Otamiser</a>
<a href="/compare/best-revenue-management-software">Best revenue management software in 2026</a>
"""
WHEELHOUSE_PAGE = '<main><h1>Otamiser vs Wheelhouse</h1><a href="https://www.usewheelhouse.com/">Wheelhouse</a></main>'


class _Resp:
    def __init__(self, text: str):
        self.text = text


@pytest.fixture
def seeded(monkeypatch: pytest.MonkeyPatch, superuser: psycopg.Connection):  # noqa: ANN201
    pages = {
        "https://www.otamiser.com/compare": HUB,
        "https://www.otamiser.com/compare/otamiser-vs-wheelhouse": WHEELHOUSE_PAGE,
    }
    monkeypatch.setattr(
        catalog, "safe_fetch", lambda url, **_: _Resp(pages.get(url, "<main></main>"))
    )
    before = {
        r[0] for r in superuser.execute("SELECT id FROM app.competitors").fetchall()
    }
    result = catalog.seed_catalog()
    new = superuser.execute(
        "SELECT name, canonical_domain, status FROM app.competitors WHERE NOT (id = ANY(%s))",
        (list(before),),
    ).fetchall()
    yield result, new
    superuser.execute(
        "DELETE FROM app.competitors WHERE NOT (id = ANY(%s))", (list(before),)
    )


def test_seed_counts_every_hub_page(seeded) -> None:  # noqa: ANN001
    result, _ = seeded
    assert result["total_pages_discovered"] == 3


def test_seed_never_marks_articles_as_published(
    seeded, superuser: psycopg.Connection
) -> None:  # noqa: ANN001
    assert superuser.execute(
        "SELECT count(*) FROM app.articles WHERE slug LIKE '%wheelhouse%' AND status='published'"
    ).fetchone() == (0,)


def test_seed_reads_competitor_domain_from_the_page(seeded) -> None:  # noqa: ANN001
    _, new = seeded
    assert any(d == "usewheelhouse.com" for _, d, _ in new)


def test_seed_does_not_store_otamiser_as_a_competitor(seeded) -> None:  # noqa: ANN001
    _, new = seeded
    assert all("otamiser" not in d for _, d, _ in new)


def test_seed_does_not_invent_domains_for_listicles(seeded) -> None:  # noqa: ANN001
    _, new = seeded
    assert all(not d.endswith(".internal") for _, d, _ in new)
