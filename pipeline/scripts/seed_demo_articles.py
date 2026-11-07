"""Fill the empty catalog articles (created by seed-catalog) with DEMO content, so the hub has pages to show.

No AI, no crawling. The text is a template; the competitor's table cells are PLACEHOLDER values, not
research. Every demo version is stored with source='demo' and content.demo=true, and the hub shows a
"Demo content" banner on it. Only one-to-one comparisons are filled; list pages ("best ... software")
and test leftovers are skipped.

Usage (from pipeline/):
    uv run python scripts/seed_demo_articles.py            # fill and publish
    uv run python scripts/seed_demo_articles.py --draft    # fill but leave unpublished
    uv run python scripts/seed_demo_articles.py --undo     # remove all demo versions again
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

import psycopg

from compare_pipeline.models_article import ArticleDraft
from compare_pipeline.render import render_article_to_webflow_html

BOOK_DEMO = "https://www.otamiser.com/"


def _db_url() -> str:
    # Settings read otamiser-prototype/.env; real environment variables (e.g. use-test-db.ps1) win.
    from compare_pipeline.config import settings

    url = os.environ.get("DATABASE_URL_MIGRATOR") or settings.DATABASE_URL_MIGRATOR
    # The pipeline role is forbidden from publishing by a DB trigger, so this script uses the migrator.
    return url.replace("postgresql+psycopg://", "postgresql://")


def clean_name(raw: str) -> str:
    """'PriceLabs Dynamic PricingRead more >' -> 'PriceLabs Dynamic Pricing'."""
    return re.sub(r"\s*Read more\s*-?>?\s*$", "", raw, flags=re.IGNORECASE).strip()


def _p(*runs: str | dict) -> dict:
    return {"runs": [{"text": r} if isinstance(r, str) else r for r in runs]}


def _b(text: str) -> dict:
    return {"text": text, "bold": True}


def _cell(state: str, text: str | None = None) -> dict:
    return {"state": state, "text_content": text}


def _pick(seed: int, options: list, n: int = 1) -> list:
    """Deterministic choice so re-running gives the same page."""
    return [options[(seed // (7**i)) % len(options)] for i in range(n)]


def build_demo(name: str, domain: str, slug: str) -> dict:
    seed = int(hashlib.sha256(domain.encode()).hexdigest(), 16)
    states = ["yes", "no", "partial", "yes", "no"]
    st = lambda i: states[(seed >> (i * 3)) % len(states)]  # noqa: E731
    partial_text = {"partial": "Limited"}

    title = f"Otamiser vs {name}: Side-by-Side Comparison"
    if len(title) > 60:
        title = f"Otamiser vs {name}"[:60]
    meta = (
        f"Compare Otamiser and {name} on OTA ranking tracking, dynamic pricing, automation "
        "and reporting for short-term rental and hotel revenue teams."
    )
    if len(meta) > 160:
        meta = f"Compare Otamiser and {name} on OTA ranking, dynamic pricing, automation and reporting for rental and hotel teams."[
            :160
        ]
    while len(meta) < 120:
        meta += " See the key differences."
    meta = meta[:160]

    focus = _pick(
        seed,
        [
            "dynamic pricing",
            "revenue management",
            "rate recommendations",
            "pricing automation",
        ],
    )[0]

    def row(feature: str, ours: dict, i: int) -> dict:
        s = st(i)
        return {
            "feature_name": feature,
            "baseline_cell": ours,
            "competitor_cell": _cell(s, partial_text.get(s)),
        }

    draft = {
        "demo": True,
        "title": title,
        "meta_description": meta,
        "slug": slug,
        "competitor_name": name,
        "competitor_domain": domain,
        "intro": [
            _p(
                "Both ",
                _b("Otamiser"),
                " and ",
                _b(name),
                f" help accommodation businesses with {focus}, but they approach it differently. "
                "Otamiser connects pricing to how visible your listings are on the major booking sites.",
            ),
            _p(
                "This page compares what each product does, where they differ, and which kind of team each one suits."
            ),
        ],
        "competitor_overview": [
            _p(
                f"{name} ({domain}) is a {focus} tool for short-term rental and hotel operators. "
                "Its feature set, channel coverage and pricing model should be checked on its own website."
            ),
        ],
        "baseline_overview": [
            _p(
                "Otamiser tracks where each listing ranks on OTAs every day and uses that ranking data, together "
                "with demand and booking pace, to adjust prices automatically within limits you set. ",
                {"text": "Learn more on otamiser.com", "href": BOOK_DEMO},
                ".",
            ),
        ],
        "differences": [
            {
                "title": "Visibility as a pricing signal",
                "paragraphs": [
                    _p(
                        "Otamiser treats OTA search ranking as a core input: if a listing drops in search results, pricing "
                        f"and content can react before bookings fall. Check whether {name} reports ranking at all."
                    ),
                ],
            },
            {
                "title": "How price changes reach your channels",
                "paragraphs": [
                    _p(
                        "Otamiser applies changes automatically inside per-listing minimum and maximum guardrails. "
                        f"Some tools, possibly including {name}, rely on manual review of each recommendation."
                    ),
                ],
            },
            {
                "title": "Reporting",
                "paragraphs": [
                    _p(
                        "Otamiser adds ranking trend reports next to occupancy and rate reports, so you can see whether "
                        "visibility or price explains a change in bookings."
                    ),
                ],
            },
        ],
        "comparison_table": [
            {
                "category_name": "Pricing",
                "rows": [
                    row("Daily dynamic pricing", _cell("yes"), 0),
                    row("Automatic price push to channels", _cell("yes"), 1),
                    row("Min / max price guardrails", _cell("yes"), 2),
                ],
            },
            {
                "category_name": "Visibility & ranking",
                "rows": [
                    row("OTA search rank tracking", _cell("yes"), 3),
                    row("Ranking drop alerts", _cell("yes"), 4),
                ],
            },
            {
                "category_name": "Service & setup",
                "rows": [
                    row("Managed revenue service option", _cell("yes"), 5),
                    row("Occupancy and pace reporting", _cell("yes"), 6),
                ],
            },
        ],
        "who_is_it_for": [
            _p(
                _b(f"{name}"),
                f" may suit teams that want a standalone {focus} tool and are happy to manage visibility separately.",
            ),
            _p(
                _b("Otamiser"),
                " suits operators who want pricing and OTA visibility handled together, with automation they can limit.",
            ),
        ],
        "pricing_analysis": [
            _p(
                f"Compare total cost at your listing count: check {name}'s current pricing page and ask Otamiser for a quote after a demo."
            ),
        ],
        "faqs": [
            {
                "question": f"Does {name} track OTA search ranking?",
                "answer": [
                    _p(
                        f"This is demo content, so it has not been checked. See {name}'s website for its current features."
                    )
                ],
            },
            {
                "question": "Can I limit how far Otamiser moves my prices?",
                "answer": [
                    _p(
                        "Yes. You set minimum and maximum prices per listing, and automatic changes stay inside them."
                    )
                ],
            },
            {
                "question": f"Can I switch from {name} to Otamiser?",
                "answer": [
                    _p(
                        "Yes. Connect your channel manager, set your guardrails, and run both side by side on a few listings first."
                    )
                ],
            },
            {
                "question": "Is there a free trial or demo?",
                "answer": [
                    _p(
                        "Otamiser offers a free demo with a ranking snapshot of your portfolio."
                    )
                ],
            },
        ],
        "cta_heading": "See where your listings rank today",
        "cta_description": "Book a free demo and get a ranking snapshot of your portfolio.",
        "cta_button_text": "Book a free demo",
        "cta_button_url": BOOK_DEMO,
    }
    ArticleDraft.model_validate(
        {k: v for k, v in draft.items() if k != "demo"}
    )  # same shape as AI drafts
    return draft


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--draft", action="store_true", help="fill but do not publish")
    ap.add_argument(
        "--undo",
        action="store_true",
        help="remove every demo version and unpublish those articles",
    )
    args = ap.parse_args()

    with psycopg.connect(_db_url()) as db:
        if args.undo:
            n = db.execute(
                """UPDATE app.articles a SET current_version_id = NULL, status = 'draft',
                          hub_published_at = NULL, hub_published_by = NULL
                   WHERE current_version_id IN (SELECT id FROM app.article_versions WHERE source = 'demo')"""
            ).rowcount
            d = db.execute(
                "DELETE FROM app.article_versions WHERE source = 'demo'"
            ).rowcount
            db.commit()
            print(f"Removed {d} demo versions; {n} articles back to empty drafts.")
            return 0

        rows = db.execute(
            """SELECT a.id, a.slug, c.id, c.name, c.canonical_domain
               FROM app.articles a JOIN app.competitors c ON c.id = a.competitor_id
               WHERE a.current_version_id IS NULL ORDER BY a.slug"""
        ).fetchall()
        filled = skipped = 0
        for art_id, slug, comp_id, raw_name, domain in rows:
            one_to_one = "-vs-" in slug and slug.count("-vs-") == 1
            if (
                not one_to_one
                or domain.endswith((".internal", ".example"))
                or "otamiser" in domain
            ):
                print(f"  skip  {slug}  (not a one-to-one competitor page)")
                skipped += 1
                continue
            name = clean_name(raw_name)
            if name != raw_name:
                db.execute(
                    "UPDATE app.competitors SET name = %s WHERE id = %s",
                    (name, comp_id),
                )
            content = build_demo(name, domain, slug)
            html = render_article_to_webflow_html(
                ArticleDraft.model_validate(
                    {k: v for k, v in content.items() if k != "demo"}
                )
            )
            gate = {
                "all_passed": False,
                "checks": {
                    "demo_content": {
                        "passed": False,
                        "details": "Demo placeholder content; not researched or fact-checked.",
                    }
                },
            }
            vid = db.execute(
                """INSERT INTO app.article_versions (article_id, version_number, content, webflow_html, gate_report, source, editor)
                   VALUES (%s, 1, %s, %s, %s, 'demo', 'seed_demo_articles') RETURNING id""",
                (art_id, json.dumps(content), html, json.dumps(gate)),
            ).fetchone()[0]
            if args.draft:
                db.execute(
                    "UPDATE app.articles SET current_version_id = %s, status = 'needs_review' WHERE id = %s",
                    (vid, art_id),
                )
            else:
                db.execute(
                    """UPDATE app.articles SET current_version_id = %s, status = 'published',
                              hub_published_at = now(), hub_published_by = 'demo-seed' WHERE id = %s""",
                    (vid, art_id),
                )
            filled += 1
            print(f"  fill  {slug}  ({name})")
        db.execute(
            """INSERT INTO app.admin_audit_log (action, entity_type, entity_id, actor, details)
               VALUES ('demo_seed', 'article', NULL, 'seed_demo_articles', %s)""",
            (json.dumps({"filled": filled, "published": not args.draft}),),
        )
        db.commit()
    print(
        f"Done: {filled} demo articles {'saved as drafts' if args.draft else 'published'}, {skipped} skipped."
    )
    print("Undo any time with: uv run python scripts/seed_demo_articles.py --undo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
