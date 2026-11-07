import json
import logging
from pathlib import Path

from compare_pipeline.models_article import ArticleDraft

logger = logging.getLogger("export_schema")

_PROTOTYPE_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = _PROTOTYPE_ROOT / "schemas"
TARGET_FILE = SCHEMAS_DIR / "article.schema.json"


def export_schema():
    """Exports Pydantic ArticleDraft schema to schemas/article.schema.json."""
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    schema = ArticleDraft.model_json_schema()
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)
    logger.info("Exported JSON schema to %s", TARGET_FILE)
    print(f"Exported article schema to {TARGET_FILE}")


if __name__ == "__main__":
    export_schema()
