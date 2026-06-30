"""Report catalogue read tool: projection through the FastMCP client."""

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


async def test_list_reports(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Report")).mock(
        return_value=httpx.Response(200, json={"reports": [{"id": 1, "name": "SLA", "x": 1}]})
    )
    data = await call(make_settings(), "list_reports", {})
    assert [r["id"] for r in data["items"]] == [1]
    assert "x" not in data["items"][0]
