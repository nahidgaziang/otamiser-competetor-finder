"""Project hygiene, configuration, facts and the validation report (guide rules 3, 4, 5; section 11)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml
from helpers import defect

from compare_pipeline.config import Settings
from compare_pipeline.discovery.dedupe import (
    extract_canonical_domain,
    is_duplicate_competitor,
    normalize_company_name,
)
from compare_pipeline.discovery.discovery import extract_homepage_evidence
from compare_pipeline.catalog import clean_competitor_name
from compare_pipeline.models import Competitor

ROOT = Path(__file__).resolve().parents[3]  # otamiser-prototype/
PIPELINE = ROOT / "pipeline"


# --- secrets & configuration -----------------------------------------------------------------------

DEFAULT_PASSWORD = re.compile(r"_pass_\d+|postgres_dev_pass")


@pytest.mark.parametrize(
    "rel",
    [
        "pipeline/src/compare_pipeline/config.py",
        "web/src/lib/db.ts",
        "compose.yaml",
    ],
)
def test_no_hard_coded_default_passwords(rel: str) -> None:
    assert not DEFAULT_PASSWORD.search((ROOT / rel).read_text(encoding="utf-8"))


def test_env_example_documents_every_setting() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    missing = [
        f
        for f in Settings.model_fields
        if f"{f}=" not in example and f != "DEFAULT_MODEL"
    ]
    assert missing == []


def test_env_file_is_git_ignored() -> None:
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gi and "!.env.example" in gi


@defect(
    "BUG-C3",
    ".gitignore contains '*AGENT*', which hides the AGENTS.md the build guide requires to be committed",
)
def test_agents_md_is_committed() -> None:
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*AGENT*" not in gi and (ROOT / "AGENTS.md").exists()


def test_web_binds_to_localhost_only() -> None:
    cfg = (ROOT / "web" / "astro.config.mjs").read_text(encoding="utf-8")
    assert "host: '127.0.0.1'" in cfg


def test_postgres_port_is_bound_to_localhost_only() -> None:
    assert '"127.0.0.1:5432:5432"' in (ROOT / "compose.yaml").read_text(
        encoding="utf-8"
    )


def test_declared_dependencies_match_imports() -> None:
    deps = " ".join(
        tomllib.loads((PIPELINE / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["dependencies"]
    )
    assert "beautifulsoup4" in deps
    assert "duckduckgo-search" not in deps


# --- Otamiser facts --------------------------------------------------------------------------------


def _facts() -> list[dict]:
    return yaml.safe_load((ROOT / "style" / "site.yaml").read_text(encoding="utf-8"))[
        "brand"
    ]["facts"]


def test_every_fact_has_id_and_public_status() -> None:
    for f in _facts():
        assert f["id"] and f["claim"] and f["status"] == "public"


def test_every_fact_cites_a_source() -> None:
    assert (ROOT / "facts" / "otamiser-facts.yaml").exists()
    assert all(
        f.get("source_url", "").startswith("https://www.otamiser.com") for f in _facts()
    )


def test_cta_points_to_a_real_otamiser_page() -> None:
    cta = yaml.safe_load((ROOT / "style" / "site.yaml").read_text(encoding="utf-8"))[
        "cta"
    ]
    assert cta["button_url"] == "https://www.otamiser.com/book-a-call-with-our-experts"


def test_minimum_portfolio_conflict_is_flagged() -> None:
    text = (ROOT / "style" / "site.yaml").read_text(encoding="utf-8").lower()
    assert "needs_decision" in text and "minimum" in text


# --- discovery helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "domain"),
    [
        ("https://app.pricelabs.co/pricing?x=1", "pricelabs.co"),
        ("WWW.Rankbreeze.COM", "rankbreeze.com"),
        ("https://sub.example.co.uk/a", "example.co.uk"),
    ],
)
def test_canonical_domain(raw: str, domain: str) -> None:
    assert extract_canonical_domain(raw) == domain


def test_company_name_normalisation_strips_suffixes() -> None:
    assert normalize_company_name("Pricepoint, Inc.") == "pricepoint"


EXISTING = [
    Competitor(name=n, canonical_domain=d, aliases=a)
    for n, d, a in [
        ("PriceLabs", "pricelabs.co", []),
        ("Revmax", "revmax.io", []),
        ("Hostaway", "hostaway.com", []),
        ("Room Raccoon", "roomraccoon.com", []),
        ("Beyond Pricing", "beyondpricing.com", ["Beyond"]),
        ("Wheelhouse", "usewheelhouse.com", []),
    ]
]


@pytest.mark.parametrize(
    ("name", "url"),
    [
        ("PriceAdvize", "https://priceadvize.com"),
        ("Revy", "https://revy.io"),
        ("Hostfully", "https://hostfully.com"),
        ("RoomPriceGenie", "https://roompricegenie.com"),
        ("Best Airbnb Pricing Tools 2026 | Blog", "https://someblog.com/post"),
    ],
)
def test_similar_but_different_companies_are_not_duplicates(
    name: str, url: str
) -> None:
    assert is_duplicate_competitor(name, url, existing_competitors=EXISTING)[0] is False


@pytest.mark.parametrize(
    ("name", "url"),
    [
        ("PriceLabs", "https://www.pricelabs.co/"),
        ("Pricelabs Inc.", "https://pricelabs-new.io"),
        ("Beyond", "https://beyond.travel"),
        ("Wheelhouse", "https://app.usewheelhouse.com/login"),
    ],
)
def test_same_company_variants_are_duplicates(name: str, url: str) -> None:
    assert is_duplicate_competitor(name, url, existing_competitors=EXISTING)[0] is True


def test_v1_fixture_includes_negative_cases() -> None:
    import json

    variants = json.loads(
        (ROOT / "fixtures" / "dedupe_variants.json").read_text(encoding="utf-8")
    )
    assert any(v["expected_duplicate"] is False for v in variants)


def test_homepage_evidence_quote_and_score() -> None:
    html = "<title>Zentrix | Pricing</title><h1>Dynamic pricing for vacation rental managers</h1>"
    title, quote, score = extract_homepage_evidence(html)
    assert title.startswith("Zentrix")
    assert "Dynamic pricing" in quote
    assert 0.0 <= score <= 1.0


def test_discovery_uses_ai_classifier() -> None:
    import inspect

    from compare_pipeline.discovery import discovery

    assert "LLMClient" in inspect.getsource(discovery)


@pytest.mark.parametrize(
    ("title", "slug", "expected"),
    [
        (
            "Otamiser Revenue Management vs Rankbreeze",
            "otamiser-vs-rankbreeze",
            "Rankbreeze",
        ),
        ("Otamiser vs Rankbreeze (2026)", "otamiser-vs-rankbreeze", "Rankbreeze"),
        (
            "Otamiser Hotel Revenue Management vs The Net Revenue",
            "otamiser-vs-the-net-revenue",
            "The Net Revenue",
        ),
        ("", "otamiser-vs-roomy-revenue", "Roomy Revenue"),
    ],
)
def test_competitor_name_from_catalog_title(
    title: str, slug: str, expected: str
) -> None:
    assert clean_competitor_name(title, slug) == expected


# --- validation report -----------------------------------------------------------------------------


def test_report_does_not_claim_unmeasured_goals_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from compare_pipeline import validation

    monkeypatch.setattr(
        validation,
        "run_validations",
        lambda: {
            "V1_dedupe_accuracy": 100.0,
            "V5_claim_accuracy": 0.0,
            "V8_ai_spend_usd": 0.0,
            "V9_anti_publish_active": True,
            "V11_ssrf_safety_pct": 100.0,
            "total_competitors": 0,
            "total_candidates": 0,
            "total_articles": 0,
        },
    )
    monkeypatch.setattr(validation, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(validation, "REPORT_FILE", tmp_path / "r.md")
    text = validation.generate_validation_report()
    v2 = next(line for line in text.splitlines() if line.startswith("| **V2**"))
    assert "PASS" not in v2, "V2 needs human relevance judgements before it can pass"
    assert "All core operational safeguards" not in text
