"""Supplier + ticket-type read tools: projection through the FastMCP client."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from fastmcp import Client

from halo_mcp.config import Settings
from halo_mcp.server import build_server

from .conftest import TEST_API_URL


def api(path: str) -> str:
    return f"{TEST_API_URL}/{path}"


async def call(settings: Settings, tool: str, args: dict[str, Any]) -> Any:
    mcp = build_server(settings)
    async with Client(mcp) as client:
        result = await client.call_tool(tool, args)
    return result.data


async def test_list_suppliers_and_get(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Supplier")).mock(
        return_value=httpx.Response(200, json={"suppliers": [{"id": 3, "name": "Dell", "x": 1}]})
    )
    respx_mock.get(api("Supplier/3")).mock(
        return_value=httpx.Response(200, json={"id": 3, "name": "Dell", "x": 1})
    )
    listing = await call(make_settings(), "list_suppliers", {})
    assert [s["id"] for s in listing["items"]] == [3]
    assert "x" not in listing["items"][0]
    one = await call(make_settings(), "get_supplier", {"id": 3})
    assert one["id"] == 3 and "x" not in one


async def test_list_ticket_types(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("TicketType")).mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "Incident", "x": 1}])
    )
    data = await call(make_settings(), "list_ticket_types", {})
    assert [t["id"] for t in data["items"]] == [1]
    assert "x" not in data["items"][0]
