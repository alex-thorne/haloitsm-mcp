"""Sites read tools: projection + filter passing through the FastMCP client."""

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


def capturing(payload: Any, sink: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    def responder(request: httpx.Request) -> httpx.Response:
        sink["params"] = dict(request.url.params)
        return httpx.Response(200, json=payload)

    return responder


async def call(settings: Settings, tool: str, args: dict[str, Any]) -> Any:
    mcp = build_server(settings)
    async with Client(mcp) as client:
        result = await client.call_tool(tool, args)
    return result.data


async def test_list_sites_projects_and_filters(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    payload = {
        "record_count": 1,
        "sites": [{"id": 5, "name": "HQ", "client_id": 2, "client_name": "Acme", "junk": 1}],
    }
    respx_mock.get(api("Site")).mock(side_effect=capturing(payload, sink))
    data = await call(make_settings(), "list_sites", {"client_id": 2, "search": "HQ"})
    assert [s["id"] for s in data["items"]] == [5]
    assert "junk" not in data["items"][0]
    assert sink["params"]["client_id"] == "2"
    assert sink["params"]["search"] == "HQ"


async def test_get_site(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Site/5")).mock(
        return_value=httpx.Response(200, json={"id": 5, "name": "HQ", "junk": 1})
    )
    data = await call(make_settings(), "get_site", {"id": 5})
    assert data["id"] == 5 and data["name"] == "HQ"
    assert "junk" not in data
