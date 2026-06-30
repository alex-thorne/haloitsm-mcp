"""Site write tools: gated; create posts, update carries an explicit id."""

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


async def test_create_site_refuses_without_confirm(
    make_settings: Callable[..., Settings],
) -> None:
    data = await run_tool(
        make_settings(enable_writes=True),
        "create_site",
        {"name": "Branch", "client_id": 2, "confirm": False},
    )
    assert data["ok"] is False
    assert data["reason"] == "confirm_required"


async def test_create_site_proceeds(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.post(api("Site")).mock(
        side_effect=body_capture(sink, {"id": 10, "name": "Branch", "client_id": 2})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "create_site",
        {"name": "Branch", "client_id": 2, "confirm": True},
    )
    assert data["ok"] is True
    assert data["site"]["id"] == 10
    assert sink["body"] == {"name": "Branch", "client_id": 2}


async def test_update_site_sends_id(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.post(api("Site")).mock(
        side_effect=body_capture(sink, {"id": 10, "name": "Branch 2"})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "update_site",
        {"id": 10, "fields": {"name": "Branch 2"}, "confirm": True},
    )
    assert data["ok"] is True
    assert sink["body"]["id"] == 10
