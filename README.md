# Competitor Intelligence & Comparison Content Engine

An automated intelligence pipeline and editorial system designed to discover market competitors, collect evidence-backed feature claims from public web sources, generate factual comparison drafts, and enforce strict quality verification before publishing.

---

## System Architecture & Workflow

The platform operates as a decoupled, queue-driven system composed of a Python processing pipeline, an ACID relational database, and an Astro SSR web interface.

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ Search Discovery│ ───>  │  Safe Fetcher   │ ───>  │ Evidence Engine │
│  (SERP Cluster) │       │ (SSRF Protected)│       │ (Quote & Tier)  │
└─────────────────┘       └─────────────────┘       └─────────────────┘
                                                             │
┌─────────────────┐       ┌─────────────────┐                ▼
│  CMS / Webflow  │ <───  │ 10-Point Gate   │ <───  ┌─────────────────┐
│   (Draft API)   │       │  Verification   │       │   LLM Writer    │
└─────────────────┘       └─────────────────┘       │ (Section Plan)  │
                                                    └─────────────────┘
```

### 1. Discovery & Canonical Deduplication
- Scans configured search query clusters across search providers.
- Normalizes URLs, cleans brand variations, and extracts registered domains (`tldextract`).
- Prevents redundant processing via canonical domain matching and fuzzy string distance (`rapidfuzz`).

### 2. Guarded Ingestion (`safe_fetch`)
- Implements strict Server-Side Request Forgery (SSRF) defense:
  - Resolves target hostnames against DNS prior to connection.
  - Rejects loopback (`127.0.0.0/8`), private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local, and cloud metadata endpoints (`169.254.169.254`).
  - Re-evaluates target IPs across every HTTP redirect.
- Enforces payload size caps (5 MB maximum) and polite per-domain request rate limiting (1 request/sec).

### 3. Evidence Extraction & Claim Attribution
- Parses competitor landing pages, pricing tables, and feature documentation.
- Extracts structured capability claims paired with exact verbatim textual quotes and source tier classifications (Tiers A through D).
- Drops claims if the attributed quote cannot be corroborated within the fetched source snapshot.

### 4. Structured Comparison Synthesis
- Composes comparison drafts using structured section-by-section prompting.
- Reconciles competitor feature sets against baseline brand capabilities.
- Produces strict JSON output adhering to a typed article schema (Pydantic).

### 5. Automated 10-Point Quality Gate
Before an article draft can advance to review, it undergoes programmatic validation:
- Schema conformance and JSON structure.
- Attribution check: 100% of factual statements must cite a verified claim quote.
- Numerical consistency: Every quantitative figure in prose must exist verbatim in cited evidence.
- Absence of uncorroborated negative claims.
- Word count, SEO title, and meta description bounds.
- HTML sanitization via strict tag/attribute allowlisting (`nh3`).

### 6. Role-Based Access & Job Management
- PostgreSQL database with least-privilege security roles:
  - `pipeline_rw`: Background worker role. Denied `DELETE` operations and prevented by database trigger from setting published status.
  - `web_app`: Admin and editorial interface role. Operates with controlled mutations and requests background jobs via stored procedures.
- Job queue backed by PostgreSQL `FOR UPDATE SKIP LOCKED` with automatic heartbeat monitoring, exponential backoff retries, and stale-job reconciliation.

---

## Technology Stack

- **Pipeline & Processing:** Python 3.12, SQLAlchemy 2.0, Alembic, Pydantic, Crawl4AI, Trafilatura, HTTPX.
- **Database:** PostgreSQL 18 (Docker containerized, SCRAM-SHA-256 authentication).
- **Web Interface:** Astro 5, Node.js SSR adapter.
- **Data Validation & Sanitization:** NH3 (Rust-based HTML sanitizer), RapidFuzz, TLDExtract.

---

## Getting Started

### Prerequisites
- Docker & Docker Compose
- Python 3.12 (`uv` package manager recommended)
- Node.js 20+

### 1. Database Setup
```bash
# Start PostgreSQL 18
docker compose up -d

# Initialize database roles and run migrations
cd pipeline
uv run python -m compare_pipeline.bootstrap_roles
uv run alembic upgrade head
```

### 2. Environment Configuration
Copy `.env.example` to `.env` and fill in local service credentials:
```bash
cp .env.example .env
```

### 3. Running the Pipeline Worker
```bash
cd pipeline
uv run python -m compare_pipeline worker
```

### 4. Running the Web Interface
```bash
cd web
npm install
npm run dev
```

### 5. Running Automated Tests
```bash
cd pipeline
uv run pytest -v
```

---

## Testing, CI and CD

- **Code review and defect list:** [`reports/code-review.md`](reports/code-review.md). Defects are tracked by tests marked as expected failures with a bug ID; remove the marker when you fix one.
- **Pipeline tests:** `cd pipeline && uv run pytest`. Integration tests need a disposable database whose name ends in `_test`; they refuse anything else.
- **Web security E2E tests:** `cd web && npm run build && npm test` (same `_test` database rule).
- **CI** (`.github/workflows/ci.yml`): lint and types, tests on PostgreSQL 18, web E2E, pip-audit, npm audit, gitleaks, Semgrep.
- **CD** (`.github/workflows/release.yml`): tag `vX.Y.Z` → full CI → GitHub Release with checksummed artifacts. The deploy job is off until hosting is set up (`HOSTING_GUIDE.md`).
- **Local hooks:** `pre-commit install` (gitleaks + ruff).

