"""Project + opportunity read tools: projection + filter passing."""

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


async def test_list_projects_filters_by_client(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Projects")).mock(
        side_effect=capturing(
            {"projects": [{"id": 7, "summary": "Rollout", "client_id": 2, "junk": 1}]}, sink
        )
    )
    data = await call(make_settings(), "list_projects", {"client_id": 2})
    assert [p["id"] for p in data["items"]] == [7]
    assert "junk" not in data["items"][0]
    assert sink["params"]["client_id"] == "2"


async def test_get_opportunity(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Opportunities/9")).mock(
        return_value=httpx.Response(200, json={"id": 9, "name": "Renewal", "junk": 1})
    )
    data = await call(make_settings(), "get_opportunity", {"id": 9})
    assert data["id"] == 9 and data["name"] == "Renewal"
    assert "junk" not in data
