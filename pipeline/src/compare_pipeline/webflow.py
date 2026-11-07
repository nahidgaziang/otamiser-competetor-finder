import logging
import re
import time
from typing import Any

import httpx

from compare_pipeline.config import settings

logger = logging.getLogger("webflow")

ALLOWED_METHODS = {"GET", "POST", "PATCH"}

ALLOWED_ENDPOINT_PAIRS = [
    ("GET", re.compile(r"^/v2/sites/[^/]+/collections$")),
    ("GET", re.compile(r"^/v2/collections/[^/]+$")),
    ("GET", re.compile(r"^/v2/collections/[^/]+/items$")),
    ("GET", re.compile(r"^/v2/collections/[^/]+/items/[^/]+$")),
    ("POST", re.compile(r"^/v2/collections/[^/]+/items/insert$")),
    ("PATCH", re.compile(r"^/v2/collections/[^/]+/items/[^/]+$")),
]

BLOCKED_PATTERNS = [
    re.compile(r"/publish", re.IGNORECASE),
    re.compile(r"/live", re.IGNORECASE),
]


class WebflowBlockedEndpointError(Exception):
    """Raised when an attempt is made to call a forbidden publishing or live endpoint."""


class WebflowDraftSafetyError(Exception):
    """Raised when an item is created or verified as non-draft."""


class WebflowOfflineError(Exception):
    """Raised when Webflow is offline or in mock mode."""


class WebflowSafeClient:
    def __init__(
        self,
        mode: str | None = None,
        token: str | None = None,
        site_id: str | None = None,
        collection_id: str | None = None,
    ):
        self.mode = mode or settings.WEBFLOW_MODE
        self.token = token or settings.WEBFLOW_API_TOKEN
        self.site_id = site_id or settings.WEBFLOW_SITE_ID
        self.collection_id = collection_id or settings.WEBFLOW_COLLECTION_ID
        self.base_url = "https://api.webflow.com"

    def _validate_request(self, method: str, path: str):
        """Strictly validates endpoint allowlist and blocks any publishing routes."""
        method_upper = method.upper()
        if method_upper not in ALLOWED_METHODS:
            raise WebflowBlockedEndpointError(
                f"HTTP method '{method_upper}' is blocked."
            )

        # Check explicit blocked patterns
        for b_pat in BLOCKED_PATTERNS:
            if b_pat.search(path):
                raise WebflowBlockedEndpointError(
                    f"Blocked endpoint: '{path}'. Automation is strictly forbidden from publishing or touching live items."
                )

        # Check allowlist as (method, path) pairs
        allowed = any(
            m == method_upper and p_pat.match(path)
            for m, p_pat in ALLOWED_ENDPOINT_PAIRS
        )
        if not allowed:
            raise WebflowBlockedEndpointError(
                f"Pair ('{method_upper}', '{path}') is not in the Webflow safe client allowlist."
            )

    def push_draft_item(
        self,
        collection_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Creates a draft item in the specified Webflow collection.
        Enforces isDraft: true and asserts draft state on response.
        """
        path = f"/v2/collections/{collection_id}/items/insert"
        self._validate_request("POST", path)

        # Offline / Mock mode
        if self.mode == "off" or not self.token:
            logger.info(
                "WEBFLOW_MODE is 'off' or token missing. Refusing draft creation."
            )
            raise WebflowOfflineError(
                "Webflow client is operating in off mode; refusing to create draft item"
            )

        payload = {
            "items": [
                {
                    "isDraft": True,
                    "isArchived": False,
                    "fieldData": fields,
                }
            ]
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        with httpx.Client(base_url=self.base_url, timeout=15.0) as client:
            resp = None
            for _attempt in range(5):
                resp = client.post(path, json=payload, headers=headers)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 1))
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                break
            if resp is None:
                raise WebflowDraftSafetyError("Failed to obtain response from Webflow")

            data = resp.json()
            if "items" in data and isinstance(data["items"], list) and data["items"]:
                item = data["items"][0]
            else:
                item = data

            if item.get("isDraft") is not True:
                raise WebflowDraftSafetyError(
                    "Security violation: Webflow item was not created as draft"
                )
            if item.get("lastPublished") is not None:
                raise WebflowDraftSafetyError(
                    "Security violation: Webflow item has lastPublished timestamp"
                )

            item_id = item.get("id")
            if item_id:
                get_path = f"/v2/collections/{collection_id}/items/{item_id}"
                self._validate_request("GET", get_path)
                try:
                    get_resp = client.get(get_path, headers=headers)
                    get_resp.raise_for_status()
                    get_data = get_resp.json()
                    if (
                        get_data.get("isDraft") is not True
                        or get_data.get("lastPublished") is not None
                    ):
                        raise WebflowDraftSafetyError(
                            "Security violation: Re-read Webflow item is not a draft or is published"
                        )
                except WebflowDraftSafetyError:
                    raise
                except Exception as exc:
                    logger.debug("Webflow item follow-up verification skipped: %s", exc)

            return item
