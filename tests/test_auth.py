"""Tests for the OAuth2 client-credentials token provider."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from halo_mcp.auth import HaloAuthError, TokenProvider
from halo_mcp.config import Settings

from .conftest import TEST_AUTH_URL, TEST_TOKEN


class FakeClock:
    """A deterministic monotonic clock for testing TTL-based refresh."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _token_response(expires_in: int = 3600) -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": TEST_TOKEN, "token_type": "Bearer", "expires_in": expires_in},
    )


async def test_token_is_fetched_once_and_cached(settings: Settings, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.post(TEST_AUTH_URL).mock(return_value=_token_response())
    async with httpx.AsyncClient() as http:
        tp = TokenProvider(settings, http)
        t1 = await tp.get_token()
        t2 = await tp.get_token()
    assert t1 == t2 == TEST_TOKEN
    assert route.call_count == 1


async def test_proactive_refresh_near_expiry(settings: Settings, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.post(TEST_AUTH_URL).mock(return_value=_token_response(expires_in=100))
    clock = FakeClock()
    async with httpx.AsyncClient() as http:
        tp = TokenProvider(settings, http, clock=clock)
        await tp.get_token()  # expires_at = 0 + 100*0.8 = 80
        clock.now = 79.0
        await tp.get_token()  # still inside the 80%% window -> cached
        assert route.call_count == 1
        clock.now = 81.0
        await tp.get_token()  # past 80%% -> proactive refresh
        assert route.call_count == 2


async def test_invalidate_forces_refresh_on_next_call(settings: Settings, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.post(TEST_AUTH_URL).mock(return_value=_token_response())
    async with httpx.AsyncClient() as http:
        tp = TokenProvider(settings, http)
        await tp.get_token()
        await tp.invalidate()  # simulates a 401 forcing re-auth
        await tp.get_token()
    assert route.call_count == 2


async def test_single_flight_under_concurrency(settings: Settings, respx_mock) -> None:  # noqa: ANN001
    route = respx_mock.post(TEST_AUTH_URL).mock(return_value=_token_response())
    async with httpx.AsyncClient() as http:
        tp = TokenProvider(settings, http)
        tokens = await asyncio.gather(*[tp.get_token() for _ in range(25)])
    assert all(t == TEST_TOKEN for t in tokens)
    assert route.call_count == 1  # no token stampede


async def test_auth_failure_raises_redacted_error(settings: Settings, respx_mock) -> None:  # noqa: ANN001
    respx_mock.post(TEST_AUTH_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    async with httpx.AsyncClient() as http:
        tp = TokenProvider(settings, http)
        with pytest.raises(HaloAuthError) as exc_info:
            await tp.get_token()
    err = exc_info.value
    assert err.status == 401
    # Neither the secret nor any token may appear anywhere in the error.
    rendered = f"{err!r} {err}"
    assert "test-client-secret" not in rendered
    assert TEST_TOKEN not in rendered


async def test_malformed_auth_response_suppresses_cause(settings: Settings, respx_mock) -> None:  # noqa: ANN001
    # A 200 body without access_token must raise, with the exception chain
    # suppressed so no fragment of the auth response body can surface.
    respx_mock.post(TEST_AUTH_URL).mock(
        return_value=httpx.Response(200, json={"not_a_token": "leakme-value"})
    )
    async with httpx.AsyncClient() as http:
        tp = TokenProvider(settings, http)
        with pytest.raises(HaloAuthError) as exc_info:
            await tp.get_token()
    assert exc_info.value.status == 200
    assert exc_info.value.__cause__ is None


async def test_request_carries_tenant_and_credentials(
    make_settings: Callable[..., Settings],
    respx_mock,  # noqa: ANN001
) -> None:
    s = make_settings(tenant="acme", scopes="read:tickets read:assets")
    captured: dict[str, str] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        captured["content_type"] = request.headers.get("content-type", "")
        return _token_response()

    respx_mock.post(TEST_AUTH_URL).mock(side_effect=responder)
    async with httpx.AsyncClient() as http:
        await TokenProvider(s, http).get_token()

    assert "tenant=acme" in captured["url"]
    assert "application/x-www-form-urlencoded" in captured["content_type"]
    assert "grant_type=client_credentials" in captured["body"]
    assert "client_id=test-client-id" in captured["body"]
    assert "client_secret=test-client-secret" in captured["body"]
    assert "scope=read" in captured["body"]
