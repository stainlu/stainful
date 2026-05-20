"""Slice 4: the runtime satisfies the golden `_core` contract and delivers the
§4 quality behaviors — driven through the hand-written tape-out SDK.
"""

from __future__ import annotations

import httpx
import pytest

# ---- runtime is importable standalone with the pinned surface ---------------


def test_runtime_public_surface():
    import stainful.runtime as rt

    for sym in (
        "SyncAPIClient", "AsyncAPIClient", "SyncAPIResource", "BaseModel",
        "make_request_options", "NotGiven", "not_given", "NOT_GIVEN", "Omit",
        "omit", "RateLimitError", "NotFoundError", "APIStatusError",
        "SyncCursorPage", "Stream", "to_raw_response_wrapper",
    ):
        assert hasattr(rt, sym), sym
    assert bool(rt.not_given) is False
    assert rt.NOT_GIVEN is rt.not_given


_AGENCY_BODY = {
    "code": 200,
    "currentTime": 1700000000,
    "text": "OK",
    "version": 2,
    "data": {
        "entry": {
            "id": "1",
            "name": "Metro",
            "timezone": "America/Los_Angeles",
            "url": "https://metro.example",
            "privateService": False,
        },
        "references": {
            "agencies": [], "routes": [], "situations": [],
            "stopTimes": [], "stops": [], "trips": [],
        },
    },
}


def _client(onebusaway, handler):
    transport = httpx.MockTransport(handler)
    return onebusaway.OnebusawaySDK(
        api_key="sek-test", http_client=httpx.Client(transport=transport)
    )


# ---- success path: model parsing, alias, request id, auth query -------------


def test_retrieve_parses_envelope_with_alias_and_request_id(golden_onebusaway):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json=_AGENCY_BODY, headers={"x-request-id": "req_abc"}
        )

    client = _client(golden_onebusaway, handler)
    resp = client.agency.retrieve("1")

    assert resp.code == 200
    assert resp.current_time == 1700000000          # camelCase alias mapped
    assert resp.data.entry.name == "Metro"
    assert resp.data.entry.private_service is False  # privateService alias
    assert resp._request_id == "req_abc"             # RESEARCH §4 #5
    assert "key=sek-test" in seen["url"]             # auth query injected
    assert "/api/where/agency/1.json" in seen["url"]


def test_empty_path_param_is_caught_before_request(golden_onebusaway):
    client = _client(golden_onebusaway, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="non-empty value for `agency_id`"):
        client.agency.retrieve("")


# ---- typed error mapping (RESEARCH §4 #4) ----------------------------------


def test_status_maps_to_typed_exception(golden_onebusaway):
    def handler(request):
        return httpx.Response(
            404, json={"error": {"code": "not_found"}},
            headers={"x-request-id": "req_404"},
        )

    client = _client(golden_onebusaway, handler)
    with pytest.raises(golden_onebusaway.NotFoundError) as exc:
        client.agency.retrieve("missing")
    assert exc.value.status_code == 404
    assert exc.value.request_id == "req_404"
    assert isinstance(exc.value, golden_onebusaway.APIStatusError)


# ---- retries with backoff (RESEARCH §4 #2) ---------------------------------


def test_retries_on_500_then_succeeds(golden_onebusaway, monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda _s: None)  # no real backoff wait
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=_AGENCY_BODY)

    client = _client(golden_onebusaway, handler)
    resp = client.agency.retrieve("1")
    assert resp.code == 200
    assert calls["n"] == 2  # one retry happened


def test_missing_api_key_is_loud(golden_onebusaway, monkeypatch):
    monkeypatch.delenv("ONEBUSAWAY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ONEBUSAWAY_API_KEY"):
        golden_onebusaway.OnebusawaySDK()


def test_with_raw_response_symbol_is_callable(golden_onebusaway):
    """`with_raw_response.<method>` returns the rich `APIResponse[T]` (was
    a pass-through pre-v0.4). Verify the symbol surface AND the wrapper
    shape — status/headers reachable, `.parse()` returns the typed model
    the SDK already validated (`.code` is a field on the model, distinct
    from the wrapper's `.status_code`)."""
    client = _client(
        golden_onebusaway, lambda r: httpx.Response(200, json=_AGENCY_BODY)
    )
    assert callable(client.agency.with_raw_response.retrieve)
    wrapped = client.agency.with_raw_response.retrieve("1")
    assert wrapped.status_code == 200
    assert wrapped.parse().code == 200
