"""Invoice + item read tools: projection + filter passing."""

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


async def test_list_invoices_filters_by_client(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Invoice")).mock(
        side_effect=capturing(
            {"invoices": [{"id": 4, "client_id": 2, "total": 99.5, "junk": 1}]}, sink
        )
    )
    data = await call(make_settings(), "list_invoices", {"client_id": 2})
    assert [i["id"] for i in data["items"]] == [4]
    assert data["items"][0]["total"] == 99.5
    assert "junk" not in data["items"][0]
    assert sink["params"]["client_id"] == "2"


async def test_list_items_and_get(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Item")).mock(
        return_value=httpx.Response(200, json={"items": [{"id": 1, "name": "Licence", "x": 1}]})
    )
    respx_mock.get(api("Item/1")).mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Licence", "x": 1})
    )
    listing = await call(make_settings(), "list_items", {})
    assert [i["id"] for i in listing["items"]] == [1]
    one = await call(make_settings(), "get_item", {"id": 1})
    assert one["id"] == 1 and "x" not in one
