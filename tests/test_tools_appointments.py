"""Appointment + attachment-metadata read tools: projection + filter passing."""

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


async def test_list_appointments_filters_by_agent(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Appointment")).mock(
        side_effect=capturing(
            {"appointments": [{"id": 2, "subject": "Visit", "agent_id": 5, "junk": 1}]}, sink
        )
    )
    data = await call(make_settings(), "list_appointments", {"agent_id": 5})
    assert [a["id"] for a in data["items"]] == [2]
    assert "junk" not in data["items"][0]
    assert sink["params"]["agent_id"] == "5"


async def test_list_attachments_filters_by_ticket(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Attachment")).mock(
        side_effect=capturing(
            {"attachments": [{"id": 8, "filename": "log.txt", "ticket_id": 7, "junk": 1}]}, sink
        )
    )
    data = await call(make_settings(), "list_attachments", {"ticket_id": 7})
    assert [a["id"] for a in data["items"]] == [8]
    assert "junk" not in data["items"][0]
    assert sink["params"]["ticket_id"] == "7"
