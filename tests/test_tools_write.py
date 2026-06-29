"""Write tools: gating, confirmation, elicitation fallback, and POST-upsert safety.

Refusal/cancel tests register NO Halo routes on purpose: respx raises on any
unexpected request, so a clean run proves no write was attempted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from halo_mcp.config import Settings
from halo_mcp.server import build_server

from .conftest import TEST_API_URL

WRITE_TOOLS = {"create_ticket", "update_ticket", "add_action", "set_ticket_status"}


def api(path: str) -> str:
    return f"{TEST_API_URL}/{path}"


async def tool_names(settings: Settings) -> set[str]:
    mcp = build_server(settings)
    async with Client(mcp) as client:
        return {t.name for t in await client.list_tools()}


async def run_tool(
    settings: Settings, tool: str, args: dict[str, Any], handler: Any | None = None
) -> Any:
    mcp = build_server(settings)
    kwargs = {"elicitation_handler": handler} if handler is not None else {}
    async with Client(mcp, **kwargs) as client:
        result = await client.call_tool(tool, args)
    return result.data


def body_capture(
    sink: dict[str, Any], response_json: Any
) -> Callable[[httpx.Request], httpx.Response]:
    def responder(request: httpx.Request) -> httpx.Response:
        sink["body"] = json.loads(request.content)
        return httpx.Response(200, json=response_json)

    return responder


async def accept_handler(message: str, response_type: Any, params: Any, context: Any) -> bool:
    return True


async def decline_handler(
    message: str, response_type: Any, params: Any, context: Any
) -> ElicitResult:
    return ElicitResult(action="decline")


# --- gating ---------------------------------------------------------------


async def test_write_tools_absent_when_disabled(make_settings: Callable[..., Settings]) -> None:
    names = await tool_names(make_settings(enable_writes=False))
    assert names.isdisjoint(WRITE_TOOLS)
    assert "list_tickets" in names  # read surface unaffected


async def test_write_tools_present_when_enabled(make_settings: Callable[..., Settings]) -> None:
    names = await tool_names(make_settings(enable_writes=True))
    assert WRITE_TOOLS <= names


# --- confirmation gate (no elicitation host) ------------------------------


async def test_create_refused_without_confirm(make_settings: Callable[..., Settings]) -> None:
    data = await run_tool(
        make_settings(enable_writes=True),
        "create_ticket",
        {"summary": "s", "details": "d", "client_id": 3, "confirm": False},
    )
    assert data["ok"] is False
    assert data["reason"] == "confirm_required"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("create_ticket", {"summary": "s", "details": "d", "client_id": 3}),
        ("update_ticket", {"id": 5, "fields": {"summary": "x"}}),
        ("set_ticket_status", {"id": 5, "status_id": 9}),
        ("add_action", {"ticket_id": 7, "note": "hi"}),
    ],
)
async def test_every_write_tool_refuses_without_confirm(
    make_settings: Callable[..., Settings], tool: str, args: dict[str, Any]
) -> None:
    # No Halo routes registered: a refusal must occur before any request.
    data = await run_tool(make_settings(enable_writes=True), tool, {**args, "confirm": False})
    assert data["ok"] is False
    assert data["reason"] == "confirm_required"


async def test_create_proceeds_with_confirm(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    route = respx_mock.post(api("Tickets")).mock(
        side_effect=body_capture(sink, {"id": 100, "summary": "s", "details": "BIG"})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "create_ticket",
        {"summary": "s", "details": "d", "client_id": 3, "ticket_type": 2, "confirm": True},
    )
    assert data["ok"] is True
    assert data["ticket"]["id"] == 100
    assert "details" not in data["ticket"]  # compact projection
    assert route.call_count == 1
    assert sink["body"] == {"summary": "s", "details": "d", "client_id": 3, "tickettype_id": 2}


# --- POST-upsert safety: updates must carry id ----------------------------


async def test_update_ticket_sends_id(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.post(api("Tickets")).mock(
        side_effect=body_capture(sink, {"id": 5, "summary": "new"})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "update_ticket",
        {"id": 5, "fields": {"summary": "new"}, "confirm": True},
    )
    assert data["ok"] is True
    assert sink["body"]["id"] == 5
    assert sink["body"]["summary"] == "new"


async def test_set_ticket_status_sends_id_and_status(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.post(api("Tickets")).mock(side_effect=body_capture(sink, {"id": 5, "status_id": 9}))
    data = await run_tool(
        make_settings(enable_writes=True),
        "set_ticket_status",
        {"id": 5, "status_id": 9, "confirm": True},
    )
    assert data["ok"] is True
    assert sink["body"] == {"id": 5, "status_id": 9}


async def test_add_action_posts_note(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.post(api("Actions")).mock(
        side_effect=body_capture(sink, {"id": 11, "ticket_id": 7, "note": "hello"})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "add_action",
        {"ticket_id": 7, "note": "hello", "outcome": "Resolved", "confirm": True},
    )
    assert data["ok"] is True
    assert data["action"]["id"] == 11
    assert sink["body"] == {"ticket_id": 7, "note": "hello", "outcome": "Resolved"}


# --- elicitation: capability-checked, with confirm-flag fallback ----------


async def test_elicitation_accept_proceeds(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    route = respx_mock.post(api("Tickets")).mock(
        return_value=httpx.Response(200, json={"id": 1, "summary": "s"})
    )
    data = await run_tool(
        make_settings(enable_writes=True),
        "create_ticket",
        {"summary": "s", "details": "d", "client_id": 3, "confirm": True},
        handler=accept_handler,
    )
    assert data["ok"] is True
    assert route.call_count == 1


async def test_elicitation_decline_cancels_without_writing(
    make_settings: Callable[..., Settings],
) -> None:
    # No Halo routes registered: if a write were attempted, respx would raise.
    data = await run_tool(
        make_settings(enable_writes=True),
        "create_ticket",
        {"summary": "s", "details": "d", "client_id": 3, "confirm": True},
        handler=decline_handler,
    )
    assert data["ok"] is False
    assert data["reason"] == "cancelled"
