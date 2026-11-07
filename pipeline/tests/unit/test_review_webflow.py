"""Webflow safe client (validation goals V9/V10; proposal 5.3, 7.3; build guide 9.6)."""

from __future__ import annotations

import json

import pytest
import respx

from compare_pipeline import webflow
from compare_pipeline.webflow import WebflowBlockedEndpointError, WebflowSafeClient

INSERT_URL = "https://api.webflow.com/v2/collections/col1/items/insert"
FIELDS = {
    "name": "Otamiser vs Zentrix",
    "slug": "otamiser-vs-zentrix",
    "body": "<p>x</p>",
}


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend a test-site token is configured so the client makes (mocked) HTTP calls."""
    monkeypatch.setattr(webflow.settings, "WEBFLOW_MODE", "test")
    monkeypatch.setattr(webflow.settings, "WEBFLOW_API_TOKEN", "test-token")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v2/collections/c1/items/publish"),
        ("POST", "/v2/sites/s1/publish"),
        ("POST", "/v2/collections/c1/items/live"),
        ("PATCH", "/v2/collections/c1/items/live"),
        ("DELETE", "/v2/collections/c1/items/live"),
        ("PATCH", "/v2/collections/c1/items/i1/live"),
        ("POST", "/v2/collections/c1/items/PUBLISH"),
        ("DELETE", "/v2/collections/c1/items/i1"),
        ("PUT", "/v2/collections/c1/items/i1"),
        ("POST", "/v2/webhooks"),
        ("GET", "/v2/sites/s1/custom_code"),
    ],
)
def test_publish_live_and_unlisted_calls_are_blocked(method: str, path: str) -> None:
    with pytest.raises(WebflowBlockedEndpointError):
        WebflowSafeClient()._validate_request(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v2/sites/s1/collections"),
        ("GET", "/v2/collections/c1"),
        ("GET", "/v2/collections/c1/items"),
        ("GET", "/v2/collections/c1/items/i1"),
        ("POST", "/v2/collections/c1/items/insert"),
        ("PATCH", "/v2/collections/c1/items/i1"),
    ],
)
def test_documented_draft_operations_are_allowed(method: str, path: str) -> None:
    WebflowSafeClient()._validate_request(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", "/v2/collections/c1"),  # would edit the collection schema
        ("POST", "/v2/collections/c1/items/i1"),
        ("POST", "/v2/sites/s1/collections"),  # would create a collection
    ],
)
def test_method_and_path_are_allowlisted_as_pairs(method: str, path: str) -> None:
    with pytest.raises(WebflowBlockedEndpointError):
        WebflowSafeClient()._validate_request(method, path)


@respx.mock
def test_blocked_call_never_reaches_the_network(live_mode: None) -> None:
    route = respx.post("https://api.webflow.com/v2/sites/s1/publish").respond(200)
    client = WebflowSafeClient()
    with pytest.raises(WebflowBlockedEndpointError):
        client._validate_request("POST", "/v2/sites/s1/publish")
    assert route.call_count == 0


@respx.mock
def test_draft_request_always_sets_is_draft(live_mode: None) -> None:
    route = respx.post(INSERT_URL).respond(
        202, json={"id": "i1", "isDraft": True, "lastPublished": None}
    )
    WebflowSafeClient().push_draft_item("col1", FIELDS)
    body = json.loads(route.calls.last.request.content)
    items = body.get("items", [body])
    assert all(i["isDraft"] is True and i["isArchived"] is False for i in items)


@respx.mock
def test_non_draft_response_is_refused(live_mode: None) -> None:
    respx.post(INSERT_URL).respond(
        202,
        json={"id": "i1", "isDraft": False, "lastPublished": "2026-11-07T00:00:00Z"},
    )
    with pytest.raises(Exception):  # noqa: B017 - any refusal is acceptable here
        WebflowSafeClient().push_draft_item("col1", FIELDS)


@respx.mock
def test_insert_request_uses_items_array(live_mode: None) -> None:
    route = respx.post(INSERT_URL).respond(
        202, json={"items": [{"id": "i1", "isDraft": True, "lastPublished": None}]}
    )
    WebflowSafeClient().push_draft_item("col1", FIELDS)
    body = json.loads(route.calls.last.request.content)
    assert isinstance(body.get("items"), list) and body["items"][0]["fieldData"]["slug"]


@respx.mock
def test_items_array_response_is_understood(live_mode: None) -> None:
    respx.post(INSERT_URL).respond(
        202, json={"items": [{"id": "i1", "isDraft": True, "lastPublished": None}]}
    )
    res = WebflowSafeClient().push_draft_item("col1", FIELDS)
    assert res["id"] == "i1"


@respx.mock
def test_created_item_is_re_read_and_checked(live_mode: None) -> None:
    respx.post(INSERT_URL).respond(
        202, json={"items": [{"id": "i1", "isDraft": True, "lastPublished": None}]}
    )
    get_route = respx.get(
        "https://api.webflow.com/v2/collections/col1/items/i1"
    ).respond(200, json={"id": "i1", "isDraft": True, "lastPublished": None})
    WebflowSafeClient().push_draft_item("col1", FIELDS)
    assert get_route.call_count == 1


def test_draft_safety_checks_do_not_rely_on_assert() -> None:
    import inspect

    assert "assert " not in inspect.getsource(WebflowSafeClient.push_draft_item)


def test_off_mode_does_not_pretend_to_create_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(webflow.settings, "WEBFLOW_MODE", "off")
    try:
        res = WebflowSafeClient().push_draft_item("col1", FIELDS)
    except Exception:  # noqa: BLE001 - refusing is the correct behaviour
        return
    assert not str(res.get("id", "")).startswith("wf_draft_")


@respx.mock
def test_rate_limit_is_retried(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)
    respx.post(INSERT_URL).mock(
        side_effect=[
            __import__("httpx").Response(429, headers={"Retry-After": "1"}),
            __import__("httpx").Response(
                202,
                json={"items": [{"id": "i1", "isDraft": True, "lastPublished": None}]},
            ),
        ]
    )
    res = WebflowSafeClient().push_draft_item("col1", FIELDS)
    assert res["id"] == "i1"
