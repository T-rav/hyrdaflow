"""FakeHTTP unit tests — route-table stubbing."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_http import FakeHTTP
from tests.scenarios.ports import HTTPPort


def test_fake_http_satisfies_port() -> None:
    assert isinstance(FakeHTTP(), HTTPPort)


async def test_routed_response_returns_scripted_body() -> None:
    fake = FakeHTTP()
    fake.when("POST", "https://api.github.com/gists").respond(
        status_code=201, json={"html_url": "https://gist.example/x"}
    )
    resp = await fake.request("POST", "https://api.github.com/gists", json={})
    assert resp.status_code == 201
    assert resp.json() == {"html_url": "https://gist.example/x"}


async def test_unrouted_request_raises() -> None:
    fake = FakeHTTP()
    with pytest.raises(LookupError, match="no route"):
        await fake.request("GET", "https://example.com/nope")


async def test_multiple_responses_pop_in_order() -> None:
    fake = FakeHTTP()
    (
        fake.when("GET", "https://api.example/x")
        .respond(status_code=500, json={})
        .respond(status_code=200, json={"ok": True})
    )
    r1 = await fake.request("GET", "https://api.example/x")
    r2 = await fake.request("GET", "https://api.example/x")
    assert r1.status_code == 500
    assert r2.status_code == 200


async def test_records_requests() -> None:
    fake = FakeHTTP()
    fake.when("GET", "https://api.example/ping").respond(status_code=204, json=None)
    await fake.request("GET", "https://api.example/ping", headers={"X-Trace": "1"})
    assert len(fake.requests) == 1
    assert fake.requests[0].method == "GET"
    assert fake.requests[0].headers == {"X-Trace": "1"}
