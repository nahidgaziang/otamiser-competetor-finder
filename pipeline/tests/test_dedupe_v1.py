import json
from pathlib import Path

from compare_pipeline.discovery.dedupe import is_duplicate_competitor
from compare_pipeline.models import Competitor


def test_v1_deduplication_variants():
    """Validates Goal V1: All 15 deduplication variants correctly detect existing competitors."""
    fixture_path = (
        Path(__file__).resolve().parent.parent.parent
        / "fixtures"
        / "dedupe_variants.json"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        variants = json.load(f)

    assert len(variants) >= 15, "Expected at least 15 test variants for Goal V1"

    # Known existing competitors with their canonical domains and aliases
    existing_comps = [
        Competitor(name="Pricepoint", canonical_domain="pricepoint.co", aliases=[]),
        Competitor(
            name="Beyond Pricing",
            canonical_domain="beyondpricing.com",
            aliases=["Beyond", "beyond.com"],
        ),
        Competitor(
            name="Wheelhouse",
            canonical_domain="usewheelhouse.com",
            aliases=["UseWheelhouse"],
        ),
        Competitor(name="Rankbreeze", canonical_domain="rankbreeze.com", aliases=[]),
        Competitor(name="AirDNA", canonical_domain="airdna.co", aliases=[]),
        Competitor(name="Hostaway", canonical_domain="hostaway.com", aliases=[]),
        Competitor(
            name="Guesty", canonical_domain="guesty.com", aliases=["Guesty for Hosts"]
        ),
        Competitor(name="PriceLabs", canonical_domain="pricelabs.co", aliases=[]),
        Competitor(name="Revolvio", canonical_domain="revolvio.com", aliases=[]),
        Competitor(
            name="OTA Insight",
            canonical_domain="otainsight.com",
            aliases=["Lighthouse", "mylighthouse.com"],
        ),
    ]

    passed_count = 0
    for v in variants:
        is_dup, matched_name, reason = is_duplicate_competitor(
            candidate_name=v["input_name"],
            candidate_domain_or_url=v["input_url"],
            existing_competitors=existing_comps,
        )
        assert is_dup == v["expected_duplicate"], (
            f"Failed on variant {v['match_type']}: name={v['input_name']}, url={v['input_url']}. "
            f"Expected {v['expected_duplicate']}, got {is_dup}. Reason: {reason}"
        )
        passed_count += 1

    assert passed_count == len(variants)
    print("V1 Deduplication: 15/15 variants passed (100% accuracy)")
