# Code review and verification: otamiser-prototype

**Date:** 7 November 2026 · **Scope:** every tracked file in `otamiser-prototype/` (7 commits, 79 files) checked against `BUILD_GUIDE.md` and the proposal.
**Audience:** the coding agent that will fix these issues, and the project owner.

## 1. Verdict

The prototype has the right **shape**: a Postgres job queue with `SKIP LOCKED`, separate database roles, a publish-blocking trigger, a quality gate, a Webflow endpoint allowlist, an SSRF guard and an HTML sanitiser. Several of these work as intended and are now covered by tests.

It cannot yet **validate the architecture**, for three reasons:

1. **The validation report is mostly hard-coded.** V2, V3, V4, V6, V7, V10 and V12 print "PASS" without measuring anything. V9 and V11 record fixed values. The status line "All core operational safeguards … passed" is fixed text. ([BUG-V1](#bug-v1))
2. **The two central evidence claims are untested in practice.** Research uses regex, so every quote is cut from the page itself and verification can never fail ([BUG-R3](#bug-r3)). The fuzzy matcher also accepts altered quotes, including changed prices and removed negations ([BUG-R1](#bug-r1)). No real AI call has ever run: there is no API key in `.env`, so every draft is the canned mock ([BUG-L2](#bug-l2)).
3. **The admin can be bypassed.** Live tests against the built server published a gate-failed draft **without logging in** ([BUG-WEB7](#bug-web7)), opened `/admin` with a forged cookie ([BUG-WEB3](#bug-web3)), and read unpublished drafts on the public hub ([BUG-WEB1](#bug-web1)).

**Keep it on localhost and don't use real data until the P0 items are fixed.**

## 2. What was done

| Check | Result |
|---|---|
| Read every source, migration, config, test and web file | Done |
| Agent's own tests (32) | All pass, but they cover happy paths only and rely on the gate bypass (BUG-G1) |
| New pipeline tests: `pipeline/tests/unit`, `pipeline/tests/integration` | **197 passed, 72 expected failures** (each is a confirmed defect) |
| New web E2E tests: `web/tests/security.test.ts` (built server + test DB) | **6 passed, 12 expected failures** |
| Pipeline line coverage | 73% → **82%** |
| `ruff check` / `ruff format` | Clean, with a documented per-file baseline for 11 pre-existing findings (see `pyproject.toml`) |
| `mypy src` | **66 errors** (BUG-Q2), informational in CI |
| `astro check` | 0 errors |
| `pip-audit` / `npm audit` | No known vulnerabilities |
| `gitleaks` (full history) | 1 false positive, triaged in `.gitleaksignore` |
| Migrations | Upgrade → downgrade → upgrade round-trip works |
| Workflows | `actionlint` + `shellcheck` clean |

**How defect tests work.** Every defect test asserts the **correct** behaviour and is marked as an expected failure (`pytest.mark.xfail(strict=True)` in Python, `it.fails` in Vitest) with its bug ID. CI stays green while the defects are open. When a defect is fixed, its test starts passing, the suite fails on purpose, and the marker must be removed. That is how a fix is proven.

## 3. Findings

Severity: **P0** = security, or publishing safety broken; **P1** = invalidates a validation goal or core claim; **P2** = wrong behaviour with limited impact; **P3** = hygiene.

### P0: fix first

<a id="bug-web7"></a>**BUG-WEB7. Admin actions run before the auth check.** `web/src/middleware.ts:7` calls `await next()` (rendering the page and running its POST handler) and only then checks the cookie (lines 17–23). A POST to `/admin/articles/{id}` with `action=publish` and no cookie published the article; the user only got the redirect afterwards. *Verified live.* **Fix:** check auth before `next()`, and re-check inside every handler.

<a id="bug-web3"></a>**BUG-WEB3 / WEB4 / WEB5 / WEB6. Fake authentication.** `web/src/pages/admin/login.astro:10–11` hard-codes `admin@otamiser.local` / `admin123` and prints them on the page (line 105). The session cookie is the constant `authenticated_admin_session_token`, and the middleware accepts **any** value for `admin_session`. *Verified live: `admin_session=x` gives a 200 on `/admin`.* **Fix:** use Better Auth as the build guide (section 8) requires: one admin created by CLI with a hashed password, sign-up disabled, random server-side sessions, 8-hour expiry.

<a id="bug-web8"></a>**BUG-WEB8. `/api/*` has no authentication.** The middleware only covers `/admin`. `web/src/pages/api/candidate-action.ts` and `trigger-job.ts` are open. *Verified live: a candidate was skipped without a session.* **Fix:** protect `/api/admin/*` (move the routes there) in middleware and in the handler.

<a id="bug-web1"></a>**BUG-WEB1. The public hub serves unpublished drafts.** `web/src/pages/compare/[slug].astro:8–16` queries `app.articles` with no status filter. `compare/index.astro:13–24` also falls back to listing **all** articles if its query errors. *Verified live.* **Fix:** read only from `app.published_articles`, and remove the fallback.

<a id="bug-web9"></a>**BUG-WEB9 / BUG-J2. Publishing and pushing to Webflow ignore the gate.** The publish handler in `admin/articles/[id].astro` never checks `gate_report.all_passed` or `gate_stale`. `worker.py:113–139` (`handle_push_webflow`) also sends drafts whose gate failed. **Fix:** server-side checks for a passing, non-stale gate on the current version, as the guide requires.

<a id="bug-g1"></a>**BUG-G1. Gate backdoor.** `pipeline/src/compare_pipeline/gate.py:100` skips verification for any `claim_id` starting with `claim-sample`. The canned mock article uses these IDs, which is why it "passes". **Fix:** delete the exception, and make tests use real claim IDs (see `tests/helpers.py`).

<a id="bug-r1"></a>**BUG-R1. Quote verification accepts altered quotes.** `research.py:36–37` uses `fuzz.partial_ratio >= 90`. A page saying "$29" verifies quotes saying "$39" or "$299", and "does not react" verifies "does react". **Fix:** exact normalised substring match first; allow fuzzy only for whitespace and punctuation, never for digits or negations; use ≥ 95 as the proposal states.

<a id="bug-s5"></a>**BUG-S5. The crawler bypasses SSRF protection.** `crawl.py:135–141` sends every URL to Crawl4AI's browser before any `safe_fetch` check, with no robots.txt check and no rate limit. **Fix:** call `validate_target_url()` (and a robots check) before any fetcher, and block private addresses in the browser config.

### P1: invalidates validation results

<a id="bug-v1"></a>**BUG-V1. Validation report is hard-coded.** `validation.py:140–181` (see section 1). **Fix:** each row shows a measured value or "NOT MEASURED". Human-judged goals (V2, V5 sample, V6, V12) read from the YAML inputs described in guide section 11.

<a id="bug-r3"></a>**BUG-R3. Research doesn't use the AI model.** `research.py:55–125` extracts claims with regex and builds each "quote" from the same page text, so V5 measures nothing. **Fix:** model extraction into a strict schema, then independent verification against the snapshot.

<a id="bug-l2"></a>**BUG-L2 to BUG-L6. The AI layer can't make a real call reliably.**
- `llm.py:94–111` silently returns a canned "Sample Competitor" article with invented claims when there's no key (L2).
- `:129` reads `content[0].text`, but Haiku 5.5 thinks by default, so the first block can be a thinking block. When that crash happens the call is never logged, so spend is under-counted (L3).
- No `output_config.format` schema is sent (L4).
- `max_tokens=4096` is too small for a full article as JSON (L5).
- There's no prompt-size check (L6).

**Fix:** raise an error when the key is missing (keep a mock only as an explicit test fixture); use the SDK's structured-output feature; select the text block by type; set `max_tokens` to at least 16k with streaming; log the call before parsing.

<a id="bug-l1"></a>**BUG-L1. Wrong AI prices.** `pipeline/config/models.yaml` prices Haiku 5.5 at $1/$5 and Sonnet 5.5 at $3/$15. The published prices are $0.10/$0.50 and $2/$10, so V8 overstates costs about 10×.

**BUG-G2 to G8. Gate gaps:**
- It passes without a DB session (fails open) (G2).
- FAQ answers and the who-it's-for / pricing / results sections are never source-checked (G3).
- Table cells are never source-checked (G4).
- A ✕ labelled "Not listed", or carrying an unverified model-written quote, passes. The proposal (4.4) requires "partial" with "Not listed" when there's no explicit evidence (G5).
- Number grounding is a substring test, so "39" matches "$399", and the numbers 1–5, 7 and 24 are exempt (G6).
- The slug isn't checked against `^otamiser-vs-` (G7).
- There's no AI checker pass (G8).

**BUG-K1 to K6. Facts and catalog:**
- Otamiser facts live in `style/site.yaml` with no source URLs, and several are embellished. The 15-vs-20 minimum isn't flagged (K1, K3).
- The CTA points to `/book-demo`, which doesn't exist; the real page is `/book-a-call-with-our-experts` (K2).
- `catalog.py:73–86` guesses competitor domains from slugs (`wheelhouse.com` instead of the page's real link, `usewheelhouse.com`) (K4).
- `pricing-tool-vs-in-house-vs-otamiser` stores Otamiser itself as a competitor (K5).
- Listicles become fake competitors with `.internal` domains (K6).

These break V1 (deduplication against the real 41 pages).

**BUG-D1 / D2. Discovery:** classification is a keyword regex, not the AI classifier with a rubric (D1). The V1 fixture has 15 positive cases and **0 negative ones**, so false positives are never measured (D2).

<a id="bug-j1"></a>**BUG-J1. No heartbeat during jobs.** `worker.py:185` has a comment saying it heartbeats, but nothing does. Jobs longer than 300 s are reaped and **run twice**.

### P2: wrong behaviour, limited impact

| ID | Issue | Where |
|---|---|---|
| BUG-W1 | Webflow allowlist checks methods and paths separately, so `PATCH /v2/collections/{id}` (schema edit) is allowed | `webflow.py:11–20` |
| BUG-W2 | `/items/insert` needs `{"items": [...]}`. The client sends the single-item shape and can't read the documented response | `webflow.py:74–110` |
| BUG-W3 / W6 | No follow-up GET to confirm the item is a draft; no 429 / `Retry-After` handling | `webflow.py` |
| BUG-W4 | Draft safety checks use `assert`, which `python -O` removes | `webflow.py:107–112` |
| BUG-W5 | With `WEBFLOW_MODE=off` the client invents an item ID (`wf_draft_…`), which gets stored as if real | `webflow.py:81–93` |
| BUG-CLI1 | `run push-webflow` drops `--article-id` (checks `push_webflow` but argparse gives `push-webflow`) | `__main__.py:76` |
| BUG-J3 | Generation trusts the model's slug, so two competitors given the same slug crash on the unique constraint | `generation.py:87` |
| BUG-DB1/2 | `pipeline_rw` can UPDATE and INSERT into `admin_audit_log` (forging admin actions) and can UPDATE `alembic_version` | migration line 547 |
| BUG-DB3 | `SECURITY DEFINER app.request_job` keeps PostgreSQL's default `EXECUTE` grant to PUBLIC | migration line 476 |
| BUG-DB4 | No read-only role for hub pages; the hub queries with `web_app` | `web/src/lib/db.ts` |
| BUG-DB5/6 | `request_job` accepts non-UUID or non-existent IDs, and callers can choose their own `dedupe_key` | migration lines 500–521 |
| BUG-S1–S4 | CGNAT `100.64/10` not blocked; empty Content-Type accepted; Chrome-impersonating User-Agent; robots.txt never checked | `safe_fetch.py` |
| BUG-R2 / R4 | Help-centre pages classified as tier D instead of A; competitor status not advanced after research | `crawl.py`, `research.py` |
| BUG-H1–H5 | Output differs from Otamiser's live markup: column order and class names, FAQ as `<h3>`, CTA inside the body, results never rendered, different differences heading | `render.py` |
| BUG-WEB2 | CSP `default-src 'self' 'unsafe-inline'` allows inline scripts | `middleware.ts:11–14` |
| BUG-WEB10 | Raw database error text is returned to the browser | `api/*.ts` |
| BUG-WEB11 | The server binds to `127.0.0.1` but its origin check expects `localhost`, so legitimate form posts from `http://127.0.0.1:4321` get 403 | `astro.config.mjs` |

### P3: hygiene

- **BUG-C1:** hard-coded fallback passwords in `config.py:22–33`, `web/src/lib/db.ts:5` and `compose.yaml:11`.
- **BUG-C2:** `.env.example` omits `DATABASE_URL_MIGRATOR`.
- **BUG-C3:** `.gitignore` pattern `*AGENT*` hides the `AGENTS.md` the guide requires.
- **BUG-Q1:** `bs4` is imported but `beautifulsoup4` is undeclared; the deprecated `duckduckgo-search` is declared but unused.
- **BUG-Q2:** 66 mypy errors (old-style SQLAlchemy `Column` declarations; switch to `Mapped[...]`).
- **Naming hazard:** `compare_pipeline.http` re-exports the `safe_fetch` function under the module's own name.
- **Git remote:** the prototype's remote points to the old `otamiser-competetor-finder` repo. Use a new repository before pushing.

**Missing from the build guide's scope:** the draft editor, Zod/Ajv validation on the web, Better Auth, the Firecrawl fallback, `facts/otamiser-facts.yaml`, the human-judgement inputs for V2/V5/V6/V12, and section-by-section generation using the reference articles. The three reference texts are saved but never used in prompts.

## 4. What is verified to work

- **Job queue:** dedupe by key, `SKIP LOCKED` claiming (two workers never get the same job), retry with backoff, terminal failure, the reaper, chaining.
- **Publish lock in the database:** `pipeline_rw` can't insert or update to `published`, can't set or clear `hub_published_*`, can't DELETE anything, and can't change the schema. `web_app` can't DELETE, can't touch `jobs` directly, and can't rewrite the audit log.
- **`safe_fetch`:** blocks loopback, private, link-local, metadata, IPv4-mapped IPv6 and Docker addresses; bad schemes and ports; redirects to internal addresses; more than 5 redirects; bodies over 5 MB; disallowed content types. The per-domain rate limit works.
- **Sanitiser:** escapes model text, strips `<script>`, `<img onerror>`, `javascript:` links and event handlers; adds `rel="noopener noreferrer"`; keeps the `otr-tnr` class.
- **Gate:** catches unknown fact IDs, unsourced intro paragraphs, large invented numbers, placeholders, banned words, metadata limits and short prose.
- **Webflow allowlist:** blocks publish, live, site-publish and unlisted endpoints before any network call, and sends `isDraft: true`. A non-draft response is refused.
- **Search:** fallback from `ddgs` to Tavily to Exa works, with normalised results.
- **Discovery:** respects the blocklist, known competitors and the candidate cap, and records every hit.
- **Deduplication:** no false positives on 9 similar-name cases, and correct matches on 4 variants.
- **Web:** cross-site POSTs are blocked (Astro `checkOrigin`). `noindex`, `nosniff` and `frame-ancestors 'none'` are sent. The typed `PUBLISH` confirmation and the audit entry work.

## 5. Validation goals: honest status

| Goal | Status today |
|---|---|
| V1 dedupe | Logic works on fixtures. **Not valid against the real catalog** (K4–K6), and false positives aren't measured (D2) |
| V2 relevance | Not measured (no human judgements recorded) |
| V3 search | Fallback logic tested with fakes. Not measured on real queries |
| V4 crawling | Not measured |
| V5 evidence | Not meaningful (R3), and the verifier accepts altered quotes (R1) |
| V6 writing quality | Not measured. No real model call has ever run (L2) |
| V7 gate | Partly. Several fault types slip through (G1–G8) |
| V8 cost | Wrong prices (L1); no real calls |
| V9 no auto-publish | Database and Webflow layers hold. **The web admin can publish without login (WEB7)** |
| V10 Webflow drafts | Not tested on a real site; request shape wrong (W2) |
| V11 SSRF / injection | `safe_fetch` mostly holds (S1); **the crawler bypasses it (S5)**; prompt injection untested |
| V12 workflow | Not possible yet: no draft editor |

## 6. Suggested fix order

1. **P0 (security and publishing):** WEB7, WEB3–6, WEB8, WEB1, WEB9/J2, G1, R1, S5.
2. **Make validation honest:** V1, L1–L6 (one real model call end to end), R3.
3. **Gate completeness:** G2–G8. Catalog: K4–K6 (read the domain from each page). Facts: K1–K3.
4. **The rest of P2, then P3.**

After each fix, remove the matching expected-failure marker. If the test still fails, the fix is incomplete.

## 7. Running the tests

```bash
# One-time: a disposable database (integration and E2E tests refuse any DB not named *_test)
docker compose up -d
#   create database otamiser_test; point DATABASE_URL* in your shell at .../otamiser_test
cd pipeline
uv run python -m compare_pipeline.bootstrap_roles && uv run alembic upgrade head
uv run pytest                      # unit + integration (+ the original tests)
uv run pytest tests/unit           # no database needed

cd ../web
npm ci && npm run build && npm test   # starts the built server on port 4398 against the test DB
```

**CI/CD:**
- `.github/workflows/ci.yml` runs on every push and PR. Jobs: lint and types, tests on a Postgres 18 service, web E2E, pip-audit / npm audit / gitleaks, and Semgrep (report-only).
- `.github/workflows/release.yml` publishes a GitHub Release on a `vX.Y.Z` tag, after the full CI passes. Its deploy job stays off until `DEPLOY_ENABLED=true` and a `production` environment with reviewers exists (see `HOSTING_GUIDE.md`).
- Dependabot updates arrive weekly, with a 14-day cooldown on new releases.
