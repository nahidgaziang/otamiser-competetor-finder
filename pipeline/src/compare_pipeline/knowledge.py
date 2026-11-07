from pathlib import Path
from typing import Any

import yaml

_PROTOTYPE_ROOT = Path(__file__).resolve().parents[3]
SITE_CONFIG_PATH = _PROTOTYPE_ROOT / "style" / "site.yaml"


def load_knowledge_base() -> dict[str, Any]:
    """Loads brand baseline facts, CTA metadata, and editorial style guidelines."""
    if not SITE_CONFIG_PATH.exists():
        return {
            "brand": {"name": "Otamiser", "domain": "otamiser.com", "facts": []},
            "cta": {
                "heading": "Automate Revenue",
                "button_text": "Book Demo",
                "button_url": "https://www.otamiser.com",
            },
            "style_rules": {"min_words": 900, "max_words": 1600},
        }

    with open(SITE_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_baseline_facts() -> list[dict[str, str]]:
    """Returns verified baseline brand facts with IDs."""
    kb = load_knowledge_base()
    return kb.get("brand", {}).get("facts", [])


def get_cta_config() -> dict[str, str]:
    """Returns call-to-action configuration for articles."""
    kb = load_knowledge_base()
    return kb.get("cta", {})
