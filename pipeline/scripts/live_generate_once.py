"""One controlled live test: research (no AI) -> generate (exactly ONE Claude call) -> gate -> report.

Why a script instead of the worker: the worker retries failed jobs up to 3 times, which could spend up
to three calls. This script calls the model once, never retries, and prints what it cost.

Usage (from pipeline/):
    uv run python scripts/live_generate_once.py --domain rankbreeze.com --name Rankbreeze --dry-run
    uv run python scripts/live_generate_once.py --domain rankbreeze.com --name Rankbreeze

--dry-run rehearses everything with a local stand-in instead of the model (free, no key needed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

from compare_pipeline import generation, research
from compare_pipeline.config import settings
from compare_pipeline.db import get_pipeline_session
from compare_pipeline.llm import LAST_RESPONSE_PATH, LLMClient
from compare_pipeline.models_article import ArticleDraft
from compare_pipeline.models import Competitor


def _stand_in(self: LLMClient, **kwargs: object):  # noqa: ANN202
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from helpers import make_draft

    return make_draft()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--domain", required=True, help="competitor domain, e.g. rankbreeze.com"
    )
    ap.add_argument("--name", required=True, help="competitor display name")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="use a local stand-in instead of the model",
    )
    ap.add_argument(
        "--from-file",
        metavar="JSON",
        help="replay a saved model answer (e.g. ../reports/last_llm_response.json) instead of calling the model",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="call the model even if research found no verified claims",
    )
    args = ap.parse_args()

    if args.from_file:
        saved = Path(args.from_file).read_text(encoding="utf-8")
        ArticleDraft.model_validate_json(
            saved
        )  # fail here, before touching the database
        LLMClient.generate_structured = lambda self, **kw: (
            ArticleDraft.model_validate_json(saved)
        )  # type: ignore[method-assign]  # noqa: E731
        args.dry_run = True  # no model call, no research gate
        print(f"REPLAY of {args.from_file}: the model will NOT be called.\n")
    elif args.dry_run:
        LLMClient.generate_structured = _stand_in  # type: ignore[method-assign]
        print("DRY RUN: the model will NOT be called.\n")
    elif not settings.ANTHROPIC_API_KEY:
        print(
            "ANTHROPIC_API_KEY is empty in .env. Add it (never commit it) or use --dry-run."
        )
        return 2

    # 1. Competitor row
    with get_pipeline_session() as s:
        comp = (
            s.query(Competitor)
            .filter(Competitor.canonical_domain == args.domain)
            .first()
        )
        if comp is None:
            comp = Competitor(
                name=args.name, canonical_domain=args.domain, status="approved"
            )
            s.add(comp)
            s.commit()
        comp_id = comp.id
    print(f"[1/4] Competitor: {args.name} ({args.domain}) id={comp_id}")

    # 2. Research: crawling + regex claims, no AI
    with get_pipeline_session() as s:
        res = research.run_competitor_research(s, comp_id)
    print(
        f"[2/4] Research: {res['snapshots_collected']} pages, {res['verified_claims']} verified claims, {res['rejected_claims']} rejected"
    )
    if res["verified_claims"] == 0 and not args.force and not args.dry_run:
        print(
            "Stopping before the model call: no verified claims to write from. Re-run with --force to spend the call anyway."
        )
        return 3

    # 3. Generation: the single model call (no retry)
    print(
        "[3/4] Generating draft"
        + (
            " (stand-in)"
            if args.dry_run
            else " with ONE call to " + LLMClient().model_name
        )
        + " ..."
    )
    result: dict | None = None
    try:
        with get_pipeline_session() as s:
            result = generation.generate_comparison_draft(s, comp_id)
    except Exception as exc:  # noqa: BLE001 - report and still show the cost that was logged
        print(f"      Generation FAILED: {type(exc).__name__}: {str(exc)[:900]}")
        if not args.dry_run and LAST_RESPONSE_PATH.exists():
            print(
                f"      The paid answer is saved at {LAST_RESPONSE_PATH}. Fix the fields named above by hand,\n"
                f"      then finish WITHOUT a new call:  uv run python scripts/live_generate_once.py "
                f'--domain {args.domain} --name "{args.name}" --from-file "{LAST_RESPONSE_PATH}"'
            )

    # 4. Report
    with get_pipeline_session() as s:
        call = s.execute(
            text(
                "SELECT model, prompt_tokens, completion_tokens, cost_usd, duration_ms, created_at "
                "FROM app.llm_calls ORDER BY created_at DESC LIMIT 1"
            )
        ).fetchone()
        total = s.execute(
            text("SELECT COALESCE(SUM(cost_usd), 0) FROM app.llm_calls")
        ).scalar_one()
    if call and not args.dry_run:
        print(
            f"      Logged call: {call.model}, {call.prompt_tokens} in / {call.completion_tokens} out tokens, ${float(call.cost_usd):.4f}, {call.duration_ms} ms"
        )
    print(
        f"      Total AI spend recorded: ${float(total):.4f} (cap ${settings.AI_SPEND_CAP_USD:.2f})"
    )

    if result:
        print(
            f"[4/4] Draft saved: article_id={result['article_id']} slug={result['slug']} gate_passed={result['gate_passed']} status={result['status']}"
        )
        with get_pipeline_session() as s:
            report = s.execute(
                text("SELECT gate_report FROM app.article_versions WHERE id = :v"),
                {"v": result["version_id"]},
            ).scalar_one()
        failed = {
            k: v["details"] for k, v in report["checks"].items() if not v["passed"]
        }
        for name, detail in failed.items():
            print(f"      gate FAIL {name}: {detail}")
        print(
            f"      Review it at http://localhost:4321/admin/articles/{result['article_id']}"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
