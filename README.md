# Otamiser Competitor Intelligence & Comparison Automation — Local Prototype

This repository implements a local proof of concept to validate the technical implementation architecture proposed for Otamiser.

It runs locally on a single machine against live competitor websites and real AI models to measure and record empirical validation metrics (**V1–V12**) across deduplication, search discovery, headless web research, grounded generation, automated QA gates, and Webflow CMS draft mapping.

---

## 1. Safety & Operational Constraints

1. **Strictly Draft Mode:** Automation cannot publish content. The database triggers and Webflow client enforce hardcoded draft constraints (`isDraft: true`). Only a signed-in human can publish to the local hub.
2. **Local Only:** Web app binds to `127.0.0.1:4321`. PostgreSQL binds to `127.0.0.1:5432`.
3. **No Secrets in Repo:** Secrets are loaded strictly from `.env` (git-ignored).
4. **AI Spend Cap:** Enforced hard cap of **$5.00 USD** across all prototype validation runs.

---

## 2. Deviations from the Original Proposal (Per Section 2.3)

| Proposal Specification | Local Prototype Implementation | Engineering Rationale | Validation Scope |
| :--- | :--- | :--- | :--- |
| **SQLite file in Git (3.5)** | **PostgreSQL 18** via Docker Compose | Provides a real relational database for the Admin UI and mirrors production hosting | Validates transactional relational model, triggers, and append-only audit tables. |
| **GitHub Actions cron (2.2, 6.1)** | **No automated schedules.** Manual triggers from Admin UI / CLI. | Local prototype focuses on pipeline correctness, idempotency, and job execution | Validates job queuing and state transitions. Avoids cloud runner IP blocking. |
| **GitHub Issues + Slack approvals** | **Local Admin Dashboard** (`/admin`) | Visual review interface provides a faster, clearer feedback loop | Validates human-in-the-loop editorial workflow and audit logging. |
| **Catalog sync via Webflow API** | **Public catalog seed** from `otamiser.com/compare` | No direct API access to Otamiser's production Webflow workspace | Validates 41-article deduplication logic and slug normalization. |
| **Webflow duplicate site** | **Free Webflow Starter test site** | No production workspace access; zero client risk | Validates draft item creation, schema mapping, and table embed handling. |

---

## 3. Getting Started

### Prerequisites
- **Docker Desktop** (running with WSL 2)
- **Python 3.12** (managed via `uv`)
- **Node.js 24 LTS**

### Quickstart Commands
```bash
# 1. Start local PostgreSQL 18
docker compose up -d

# 2. Setup Python environment
cd pipeline
uv sync
uv run python -m compare_pipeline run seed-catalog

# 3. Setup Web frontend
cd ../web
npm install
npm run dev
```

