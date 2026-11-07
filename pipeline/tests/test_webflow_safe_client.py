import pytest

from compare_pipeline.webflow import WebflowBlockedEndpointError, WebflowSafeClient


def test_webflow_blocks_publish_and_live_endpoints():
    """Validates Goal V9: Client-level blocking of publishing endpoints."""
    client = WebflowSafeClient()

    blocked_paths = [
        "/v2/collections/col123/items/publish",
        "/v2/sites/site123/publish",
        "/v2/collections/col123/items/live",
        "/v2/collections/col123/items/item123/live",
    ]

    for path in blocked_paths:
        with pytest.raises(WebflowBlockedEndpointError) as exc_info:
            client._validate_request("POST", path)
        assert "blocked" in str(exc_info.value).lower()


def test_webflow_blocks_unlisted_endpoints():
    """Validates that arbitrary unlisted endpoints are rejected by the allowlist."""
    client = WebflowSafeClient()

    unlisted_paths = [
        "/v2/users",
        "/v2/webhooks",
        "/v2/custom_code",
    ]

    for path in unlisted_paths:
        with pytest.raises(WebflowBlockedEndpointError) as exc_info:
            client._validate_request("POST", path)
        assert "allowlist" in str(exc_info.value).lower()


def test_webflow_push_draft_enforces_draft_payload():
    """Validates that items are created strictly as drafts (lastPublished is None)."""
    client = WebflowSafeClient()
    fields = {
        "name": "Otamiser vs Sample",
        "slug": "otamiser-vs-sample",
        "body": "<p>Content</p>",
    }

    res = client.push_draft_item("col123", fields)
    assert res["isDraft"] is True
    assert res["lastPublished"] is None
    assert res["fieldData"]["slug"] == "otamiser-vs-sample"
