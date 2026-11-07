"""Integration tests run against a real, migrated PostgreSQL database.

They must never run against the developer's working database: the session fixture refuses
unless the database name ends in "_test" (CI uses otamiser_test; locally, point the
DATABASE_URL* variables at a disposable otamiser_test database).
"""

from __future__ import annotations

import urllib.parse
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from compare_pipeline.config import settings

pytestmark = pytest.mark.db


@pytest.fixture(scope="session", autouse=True)
def _require_test_database() -> None:
    db_name = urllib.parse.urlparse(settings.DATABASE_URL).path.lstrip("/")
    if not db_name.endswith("_test"):
        pytest.skip(
            f"Integration tests need a disposable *_test database (got '{db_name}')"
        )
    try:
        with psycopg.connect(settings.DATABASE_URL, connect_timeout=3) as conn:
            conn.execute("SELECT 1 FROM app.jobs LIMIT 1")
    except psycopg.Error as exc:
        pytest.skip(f"Test database not reachable or not migrated: {exc}")


@pytest.fixture
def superuser() -> Iterator[psycopg.Connection]:
    """Superuser connection for arranging data and cleaning up (never used by code under test)."""
    with psycopg.connect(settings.DATABASE_URL, autocommit=True) as conn:
        yield conn


@pytest.fixture
def as_pipeline() -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings.DATABASE_URL_PIPELINE, autocommit=True) as conn:
        yield conn


@pytest.fixture
def as_web() -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings.DATABASE_URL_WEB, autocommit=True) as conn:
        yield conn


@pytest.fixture
def competitor(superuser: psycopg.Connection) -> Iterator[uuid.UUID]:
    """A throwaway competitor row, deleted (with its articles, claims, snapshots) afterwards."""
    domain = f"review-{uuid.uuid4().hex[:10]}.example"
    row = superuser.execute(
        "INSERT INTO app.competitors (name, canonical_domain, status) "
        "VALUES ('Review Test Co', %s, 'candidate') RETURNING id",
        (domain,),
    ).fetchone()
    assert row is not None
    comp_id: uuid.UUID = row[0]
    yield comp_id
    superuser.execute("DELETE FROM app.competitors WHERE id = %s", (comp_id,))


@pytest.fixture(autouse=True)
def _clean_jobs(superuser: psycopg.Connection) -> Iterator[None]:
    yield
    superuser.execute(
        "DELETE FROM app.jobs WHERE requested_by IN ('review_test', 'chain', 'cli')"
    )
