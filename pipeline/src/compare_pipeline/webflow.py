import logging
import re
from typing import Any

import httpx

from compare_pipeline.config import settings

logger = logging.getLogger("webflow")

ALLOWED_METHODS = {"GET", "POST", "PATCH"}

# Allowed path patterns for Webflow CMS operations
ALLOWED_PATH_PATTERNS = [
    re.compile(r"^/v2/sites/[^/]+/collections$"),
    re.compile(r"^/v2/collections/[^/]+$"),
    re.compile(r"^/v2/collections/[^/]+/items$"),
    re.compile(r"^/v2/collections/[^/]+/items/[^/]+$"),
    re.compile(r"^/v2/collections/[^/]+/items/insert$"),
]

BLOCKED_PATTERNS = [
    re.compile(r"/publish", re.IGNORECASE),
    re.compile(r"/live", re.IGNORECASE),
]


class WebflowBlockedEndpointError(Exception):
    """Raised when an attempt is made to call a forbidden publishing or live endpoint."""


class WebflowSafeClient:
    def __init__(self):
        self.mode = settings.WEBFLOW_MODE
        self.token = settings.WEBFLOW_API_TOKEN
        self.site_id = settings.WEBFLOW_SITE_ID
        self.collection_id = settings.WEBFLOW_COLLECTION_ID
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

        # Check allowlist
        allowed = any(p_pat.match(path) for p_pat in ALLOWED_PATH_PATTERNS)
        if not allowed:
            raise WebflowBlockedEndpointError(
                f"Path '{path}' is not in the Webflow safe client allowlist."
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

        payload = {
            "isDraft": True,
            "isArchived": False,
            "fieldData": fields,
        }

        # Offline / Mock mode
        if self.mode == "off" or not self.token:
            logger.info(
                "WEBFLOW_MODE is 'off' or token missing. Simulating draft creation for %s",
                fields.get("slug"),
            )
            mock_id = f"wf_draft_{fields.get('slug', 'sample')}"
            return {
                "id": mock_id,
                "isDraft": True,
                "isArchived": False,
                "lastPublished": None,
                "fieldData": fields,
            }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        with httpx.Client(base_url=self.base_url, timeout=15.0) as client:
            resp = client.post(path, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            # Safety assertion: must be a draft and must not be published
            assert data.get("isDraft") is True, (
                "Security violation: Webflow item was not created as draft"
            )
            assert data.get("lastPublished") is None, (
                "Security violation: Webflow item has lastPublished timestamp"
            )

            return data
