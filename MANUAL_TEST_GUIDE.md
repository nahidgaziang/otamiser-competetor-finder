# Manual test guide: run the prototype locally and check it works

Commands are for **PowerShell** on Windows. Run them from the `otamiser-prototype` folder unless a step says otherwise. Allow about 45 minutes.

## 0. Before you start: what is expected to fail

These are known open bugs (review round 2, 7 Nov 2026). If you see them, the prototype is behaving as diagnosed, not newly broken:

| Bug | What you'll see |
|---|---|
| R5 | Research crawls only the homepage, so competitors end up "needs_attention" with very few claims |
| R6 | "Verified" claims contain menu and image text (`![...](https://...)`) |
| R3b, D1b | Research and discovery don't actually use the AI (regex only) |
| G8b | The gate's "ai_checker" always shows passed (it's fake) |
| K1b | Otamiser facts cite `/features` and `/about`, which don't exist on otamiser.com |
| WEB3b, WEB5b | `admin123` still logs in, and the old fixed cookie value still opens `/admin` |
| WEB9b | An article edited after its gate passed can still be published |

## 1. One-time preparation

1. Start **Docker Desktop** and wait until it says "Engine running".
2. **Stop any running `npm run dev`** for this project (Ctrl+C in its terminal). A running dev server locks files and makes `npm ci` fail with `EPERM`.
3. Check the tools:
   ```powershell
   docker --version
   node --version          # v24.x
   uv --version            # if "not recognised": $env:Path += ";$env:USERPROFILE\.local\bin"
   ```
4. Start the database and check it's healthy:
   ```powershell
   docker compose up -d
   docker ps               # otamiser_postgres ... (healthy)   127.0.0.1:5432->5432
   ```
5. Install the pipeline and prepare your **dev** database (`otamiser_local`):
   ```powershell
   cd pipeline
   uv sync --frozen --all-groups
   uv run python -m compare_pipeline.bootstrap_roles
   uv run alembic upgrade head
   cd ..
   ```

## 2. Automated tests (use a separate test database)

Open a **new PowerShell window** for this section only.

```powershell
cd C:\Users\ejena\OneDrive\Desktop\Dev\otamiser-prototype

# Create the throwaway test database (password comes from your .env, it is not printed)
$pw = ((Select-String -Path .env -Pattern '^POSTGRES_PASSWORD=').Line -split '=', 2)[1]
docker exec -e PGPASSWORD=$pw otamiser_postgres psql -U postgres -c "DROP DATABASE IF EXISTS otamiser_test WITH (FORCE);" -c "CREATE DATABASE otamiser_test;"

# Point THIS window at otamiser_test and clear all API keys
. .\scripts\use-test-db.ps1

cd pipeline
uv run python -m compare_pipeline.bootstrap_roles
uv run alembic upgrade head
uv run pytest                 # expect: 271 passed, 7 xfailed
uv run ruff check .           # expect: All checks passed!

cd ..\web
npm ci                        # expect: found 0 vulnerabilities
npm run check                 # expect: 0 errors
npm run build
npm test                      # expect: 20 passed | 3 expected fail
```

"xfailed" and "expected fail" are the tracked bugs from section 0. They are not new failures. Any plain **failed** is new, so send me the output. **Close this window when you're done**, so you don't run the app against the test database by accident.

## 3. Run the app (dev database)

Use two new PowerShell windows. **Leave `ANTHROPIC_API_KEY` empty in `.env` for this section.** If the worker failed with a key set, it would retry and could spend up to 3 calls.

**Window A: worker**
```powershell
cd C:\Users\ejena\OneDrive\Desktop\Dev\otamiser-prototype\pipeline
uv run python -m compare_pipeline worker        # leave running; it logs every job
```

**Window B: website**
```powershell
cd C:\Users\ejena\OneDrive\Desktop\Dev\otamiser-prototype\web
npm run dev                                     # http://localhost:4321
```

Open **http://localhost:4321** (use `localhost`).

## 4. Manual checklist

Tick each item as you go.

| # | Do this | Expected |
|---|---|---|
| 1 | Open `/compare` | Page loads; no articles yet (only published ones show) |
| 2 | Open `/admin` | Redirects to the login page |
| 3 | Log in: `admin@otamiser.local` / `admin123` | Admin dashboard (this login is bug WEB5b; it should be replaced) |
| 4 | Seed the catalog. There's no button for this, so in a third PowerShell window run `cd ...\otamiser-prototype\pipeline` then `uv run python -m compare_pipeline run seed-catalog` | Window A logs the job; the dashboard shows about 41 competitors |
| 5 | Jobs → run **discover** | Window A shows searches; up to 5 new candidates appear under Candidates, each with a quote |
| 6 | Candidates → **Skip** one | It disappears from the list |
| 7 | Candidates → **Approve** one | Window A runs research, then generate, which **fails** with "ANTHROPIC_API_KEY is not configured" and retries 3 times. That is correct error handling without a key |
| 8 | Articles → open any article → **Publish** without typing `PUBLISH` | Refused |
| 9 | Publish an article whose gate failed | Refused: "failed one or more automated quality gates" |
| 10 | Log out, then in PowerShell: `curl.exe -s -o NUL -w "%{http_code}" -X POST http://localhost:4321/api/trigger-job -d "kind=discover"` | `401` |
| 11 | `curl.exe -s -o NUL -w "%{http_code}" http://localhost:4321/admin -H "Cookie: admin_session=anything"` | `302` (forged cookie rejected) |
| 12 | In the browser's dev tools → Network → any page → response headers | `content-security-policy` and `x-robots-tag: noindex, nofollow` are present |

## 5. The one live AI call

**Model:** Claude Haiku 5.5 (`claude-haiku-5-5`, set in `pipeline/config/models.yaml`), at $0.10 per million input tokens and $0.50 per million output tokens.

You have one try, so this goes through a script that calls the model **exactly once and never retries**. It also stops before the call if research found nothing to write from.

1. **Stop the worker** (Ctrl+C in window A), so nothing else can call the model. Keep window B (the website) running.
2. **Rehearse for free:**
   ```powershell
   cd C:\Users\ejena\OneDrive\Desktop\Dev\otamiser-prototype\pipeline
   uv run python scripts/live_generate_once.py --domain rankbreeze.com --name Rankbreeze --dry-run
   ```
   You should see steps `[1/4]` to `[4/4]` and "DRY RUN: the model will NOT be called".
3. **Add your key** to `otamiser-prototype\.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Never commit it. `.env` is git-ignored; `git status` must not list `.env`.
4. **Run it for real** (one call; expected cost under $0.01 with Claude Haiku 5.5):
   ```powershell
   uv run python scripts/live_generate_once.py --domain rankbreeze.com --name Rankbreeze
   ```
5. **Read the output:**
   - `Logged call: claude-haiku-5-5, N in / M out tokens, $X`: the API call worked and was recorded.
   - `Draft saved: ... gate_passed=False status=needs_attention` is **expected**. Research only got the homepage and junk claims (R5, R6), and the facts are unverified (K1b), so the gate is right to refuse it.
   - Open the printed `http://localhost:4321/admin/articles/...` link. Read the preview and judge structure, tone, and whether it invents facts. Compare it with the real page at otamiser.com/compare/otamiser-vs-rankbreeze.
6. **Remove the key** from `.env` afterwards.

**If the call fails, don't retry. Send me the output:**
- `400 ... invalid_request_error`: the request shape was rejected (the schema fix didn't hold).
- `ValidationError`: the model answered but the JSON broke a rule (for example, meta description length). The call is still logged and charged once.
- `Stopping before the model call: no verified claims`: nothing was spent. Research found nothing, so try another domain.

## 6. Clean up

```powershell
docker compose stop          # keeps your data; `docker compose up -d` to resume
```
