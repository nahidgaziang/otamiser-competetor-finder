import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from compare_pipeline.db import Base


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    canonical_domain = Column(Text, nullable=False, unique=True)
    aliases = Column(ARRAY(Text), nullable=False, default=list)
    segment = Column(Text, nullable=True)
    type = Column(Text, nullable=True)
    is_partner = Column(Boolean, nullable=False, default=False)
    status = Column(Text, nullable=False, default="candidate")
    relevance_score = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)
    evidence_quote = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DiscoveryHit(Base):
    __tablename__ = "discovery_hits"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    snippet = Column(Text, nullable=True)
    domain = Column(Text, nullable=False)
    raw_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competitor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.competitors.id", ondelete="SET NULL"),
        nullable=True,
    )
    url = Column(Text, nullable=False)
    source_tier = Column(Text, nullable=False)  # 'A', 'B', 'C', 'D'
    fetcher = Column(Text, nullable=False)  # 'crawl4ai', 'trafilatura', 'firecrawl'
    content_markdown = Column(Text, nullable=False)
    sha256 = Column(Text, nullable=False)
    headers = Column(JSONB, nullable=False, default=dict)
    fetched_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competitor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.competitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.source_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    field = Column(Text, nullable=False)
    value = Column(JSONB, nullable=False)
    quote = Column(Text, nullable=False)
    tier = Column(Text, nullable=False)
    status = Column(
        Text, nullable=False, default="verified"
    )  # 'verified', 'rejected', 'conflicting'
    reject_reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competitor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.competitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug = Column(Text, nullable=False, unique=True)
    current_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "app.article_versions.id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    status = Column(
        Text, nullable=False, default="draft"
    )  # 'draft', 'needs_review', 'needs_attention', 'published', 'archived'
    hub_published_at = Column(DateTime(timezone=True), nullable=True)
    hub_published_by = Column(Text, nullable=True)
    webflow_item_id = Column(Text, nullable=True)
    webflow_last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ArticleVersion(Base):
    __tablename__ = "article_versions"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    content = Column(JSONB, nullable=False)
    webflow_html = Column(Text, nullable=False)
    gate_report = Column(JSONB, nullable=True)
    gate_stale = Column(Boolean, nullable=False, default=False)
    source = Column(Text, nullable=False, default="ai_pipeline")
    editor = Column(Text, nullable=True)
    model = Column(Text, nullable=True)
    prompt_version = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "idx_jobs_active_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index(
            "idx_jobs_claim",
            "status",
            "run_after",
            postgresql_where=text("status = 'queued'"),
        ),
        {"schema": "app"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    dedupe_key = Column(Text, nullable=True)
    status = Column(
        Text, nullable=False, default="queued"
    )  # 'queued', 'running', 'completed', 'failed'
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    run_after = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    trigger = Column(Text, nullable=False, default="manual")
    requested_by = Column(Text, nullable=False, default="system")
    error = Column(Text, nullable=True)
    result = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app.jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    stage = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    cost_usd = Column(Numeric(10, 6), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    prompt_preview = Column(Text, nullable=True)
    response_preview = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(Text, nullable=True)
    actor = Column(Text, nullable=False)
    details = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = {"schema": "app"}

    key = Column(Text, primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = {"schema": "app"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_id = Column(Text, nullable=False)
    metric_name = Column(Text, nullable=False)
    metric_value = Column(Numeric, nullable=False)
    details = Column(JSONB, nullable=True)
    recorded_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
