"""Directory write tools: gated, and updates carry an explicit id."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from fastmcp import Client

from halo_mcp.config import Settings
from halo_mcp.server import build_server

from .conftest import TEST_API_URL


def api(path: str) -> str:
    return f"{TEST_API_URL}/{path}"


def body_capture(
    sink: dict[str, Any], response_json: Any
) -> Callable[[httpx.Request], httpx.Response]:
    def responder(request: httpx.Request) -> httpx.Response:
        sink["body"] = json.loads(request.content)
        return httpx.Response(200, json=response_json)

    return responder


async def run_tool(settings: Settings, tool: str, args: dict[str, Any]) -> Any:
    mcp = build_server(settings)
    async with Client(mcp) as client:
        result = await client.call_tool(tool, args)
    return result.data


async def test_update_client_refuses_without_confirm(
    make_settings: Callable[..., Settings],
) -> None:
    # No Halo route registered: a refusal must happen before any request.
    data = await run_tool(
        make_settings(enable_writes=True),
        "update_client",
        {"id": 2, "fields": {"name": "Acme Ltd"}, "confirm": False},
    )
    assert data["ok"] is False
    assert data["reason"] == "confirm_required"


async def test_update_client_sends_id(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.post(api("Client")).mock(
        side_effect=body_capture(sink, {"id": 2, "name": "Acme Ltd"})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "update_client",
        {"id": 2, "fields": {"name": "Acme Ltd"}, "confirm": True},
    )
    assert data["ok"] is True
    assert sink["body"]["id"] == 2
    assert sink["body"]["name"] == "Acme Ltd"


async def test_update_user_sends_id(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.post(api("Users")).mock(
        side_effect=body_capture(sink, {"id": 3, "name": "Sam Smith"})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "update_user",
        {"id": 3, "fields": {"name": "Sam Smith"}, "confirm": True},
    )
    assert data["ok"] is True
    assert sink["body"]["id"] == 3
