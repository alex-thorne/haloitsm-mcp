"""Per-call timeout override threads to httpx; default uses the client default."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from halo_mcp.client import HaloClient
from halo_mcp.config import Settings


class RecordingHTTP:
    """Duck-typed stand-in for httpx.AsyncClient that records request kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        json: Any = None,
        headers: Any = None,
        timeout: Any = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "timeout": timeout})
        return httpx.Response(200, json={"ok": True})

    async def aclose(self) -> None:
        return None


async def test_explicit_timeout_is_forwarded(
    make_settings: Callable[..., Settings], stub_token: Any
) -> None:
    http = RecordingHTTP()
    client = HaloClient(make_settings(), http=http, token_provider=stub_token)
    await client.get("/Tickets", timeout=12.0)
    assert http.calls[0]["timeout"] == 12.0


async def test_absent_timeout_uses_client_default(
    make_settings: Callable[..., Settings], stub_token: Any
) -> None:
    http = RecordingHTTP()
    client = HaloClient(make_settings(), http=http, token_provider=stub_token)
    await client.get("/Tickets")
    assert http.calls[0]["timeout"] is httpx.USE_CLIENT_DEFAULT


def test_long_timeout_default(make_settings: Callable[..., Settings]) -> None:
    assert make_settings().long_timeout == 120.0
