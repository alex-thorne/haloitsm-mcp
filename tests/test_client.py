"""Tests for the async Halo HTTP client: pagination, retry/backoff, errors."""

from __future__ import annotations

import random
from typing import Any

import httpx
import pytest

from halo_mcp.client import HaloAPIError, HaloClient
from halo_mcp.config import Settings

from .conftest import TEST_API_URL


def api(path: str) -> str:
    return f"{TEST_API_URL}/{path}"


class RecordingSleep:
    """An async sleep stand-in that records durations and never actually waits."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


def client_for(settings: Settings, stub_token: Any, **kw: Any) -> HaloClient:
    kw.setdefault("sleep", RecordingSleep())
    kw.setdefault("rng", random.Random(0))
    return HaloClient(settings, token_provider=stub_token, **kw)


async def test_paginate_walks_pages_until_record_count(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    pages = {
        1: {"record_count": 3, "tickets": [{"id": 1}, {"id": 2}]},
        2: {"record_count": 3, "tickets": [{"id": 3}]},
    }

    def responder(request: httpx.Request) -> httpx.Response:
        page_no = int(request.url.params.get("page_no", "1"))
        return httpx.Response(200, json=pages[page_no])

    route = respx_mock.get(api("Tickets")).mock(side_effect=responder)
    async with client_for(settings, stub_token) as client:
        records = await client.paginate("/Tickets", collection_key="tickets", page_size=2)

    assert [r["id"] for r in records] == [1, 2, 3]
    assert route.call_count == 2


async def test_paginate_stops_at_hard_page_cap(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    # record_count always claims more than we return -> would loop forever without a cap.
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"record_count": 9999, "tickets": [{"id": 1}]})

    route = respx_mock.get(api("Tickets")).mock(side_effect=responder)
    async with client_for(settings, stub_token, max_pages=5) as client:
        records = await client.paginate("/Tickets", collection_key="tickets", page_size=1)

    assert route.call_count == 5
    assert len(records) == 5


async def test_paginate_clamps_page_size_to_halo_max(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    captured: dict[str, Any] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        captured["page_size"] = request.url.params.get("page_size")
        return httpx.Response(200, json={"record_count": 1, "tickets": [{"id": 1}]})

    respx_mock.get(api("Tickets")).mock(side_effect=responder)
    async with client_for(settings, stub_token) as client:
        await client.paginate("/Tickets", collection_key="tickets", page_size=500)

    # Halo caps list responses at 100/page; requesting more must be clamped.
    assert captured["page_size"] == "100"


async def test_paginate_falls_back_to_first_list_envelope_key(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"record_count": 1, "results": [{"id": 5}]})

    respx_mock.get(api("Agent")).mock(side_effect=responder)
    async with client_for(settings, stub_token) as client:
        records = await client.paginate("/Agent", collection_key="agents", page_size=50)

    assert [r["id"] for r in records] == [5]


async def test_forbidden_raises_typed_error_with_path(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    from halo_mcp.client import HaloForbiddenError

    respx_mock.get(api("Supplier")).mock(return_value=httpx.Response(403, json={"error": "no"}))
    async with client_for(settings, stub_token) as client:
        with pytest.raises(HaloForbiddenError) as exc:
            await client.get("/Supplier")
    assert exc.value.status == 403
    assert "Supplier" in exc.value.path


async def test_retries_on_503_with_backoff(settings: Settings, stub_token: Any, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.get(api("Status")).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    sleep = RecordingSleep()
    async with client_for(settings, stub_token, sleep=sleep) as client:
        body = await client.get("/Status")

    assert body == {"ok": True}
    assert route.call_count == 2
    assert len(sleep.calls) == 1
    assert 0.5 <= sleep.calls[0] <= 1.0  # base 0.5 + jitter in [0, 0.5]


async def test_honours_retry_after_header(settings: Settings, stub_token: Any, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.get(api("Status")).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    sleep = RecordingSleep()
    async with client_for(settings, stub_token, sleep=sleep) as client:
        await client.get("/Status")

    assert route.call_count == 2
    assert sleep.calls == [2.0]  # exact Retry-After, no jitter


async def test_retry_exhaustion_raises_typed_error(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    route = respx_mock.get(api("Status")).mock(return_value=httpx.Response(503))
    async with client_for(settings, stub_token, max_retries=2) as client:
        with pytest.raises(HaloAPIError) as exc_info:
            await client.get("/Status")

    assert exc_info.value.status == 503
    assert route.call_count == 3  # 1 initial + 2 retries


async def test_non_2xx_raises_halo_api_error_with_body(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    respx_mock.get(api("Tickets")).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    async with client_for(settings, stub_token) as client:
        with pytest.raises(HaloAPIError) as exc_info:
            await client.get("/Tickets")

    assert exc_info.value.status == 500
    assert exc_info.value.body == {"error": "boom"}


async def test_401_triggers_reauth_then_retries_once(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    route = respx_mock.get(api("Tickets/1")).mock(
        side_effect=[
            httpx.Response(401, json={"error": "token expired"}),
            httpx.Response(200, json={"id": 1, "summary": "hi"}),
        ]
    )
    async with client_for(settings, stub_token) as client:
        body = await client.get("/Tickets/1")

    assert body == {"id": 1, "summary": "hi"}
    assert stub_token.invalidated == 1
    assert route.call_count == 2


async def test_post_update_rejects_missing_id(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    async with client_for(settings, stub_token) as client:
        with pytest.raises(ValueError, match="id"):
            await client.post_update("/Tickets", {"summary": "no id -> would duplicate"})


async def test_post_update_with_id_succeeds(
    settings: Settings, stub_token: Any, respx_mock
) -> None:  # noqa: ANN001
    route = respx_mock.post(api("Tickets")).mock(
        return_value=httpx.Response(200, json={"id": 7, "summary": "patched"})
    )
    async with client_for(settings, stub_token) as client:
        result = await client.post_update("/Tickets", {"id": 7, "summary": "patched"})

    assert result == {"id": 7, "summary": "patched"}
    assert route.call_count == 1
