"""Analytics/triage tools (summarise_tickets, list_overdue_tickets) via FastMCP."""

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


async def test_summarise_tickets_groups_by_status(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    payload = {
        "record_count": 3,
        "tickets": [
            {"id": 1, "status_id": 9, "dateoccurred": "2026-06-01T09:00:00"},
            {"id": 2, "status_id": 9, "dateoccurred": "2026-06-02T09:00:00"},
            {"id": 3, "status_id": 2, "dateoccurred": "2026-06-03T09:00:00"},
        ],
    }
    respx_mock.get(api("Tickets")).mock(return_value=httpx.Response(200, json=payload))
    data = await call(make_settings(), "summarise_tickets", {"group_by": "status_id"})
    assert data["total"] == 3
    assert data["group_by"] == "status_id"
    assert data["groups"] == [{"value": 9, "count": 2}, {"value": 2, "count": 1}]
    assert set(data["age_days"]) == {"min", "median", "max", "mean"}


async def test_summarise_tickets_groups_by_priority_id(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    payload = {
        "record_count": 3,
        "tickets": [
            {"id": 1, "priority_id": 1},
            {"id": 2, "priority_id": 1},
            {"id": 3, "priority_id": 3},
        ],
    }
    respx_mock.get(api("Tickets")).mock(return_value=httpx.Response(200, json=payload))
    data = await call(make_settings(), "summarise_tickets", {"group_by": "priority_id"})
    assert data["groups"] == [{"value": 1, "count": 2}, {"value": 3, "count": 1}]


async def test_summarise_tickets_rejects_unknown_group_by(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    data = await call(make_settings(), "summarise_tickets", {"group_by": "nonsense"})
    assert data["error"] == "invalid_group_by"
    assert "status_id" in data["allowed"]


async def test_list_overdue_tickets_flags_response_and_fix_breaches(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    payload = {
        "record_count": 3,
        "tickets": [
            # A: first-response deadline long past, never responded -> response breach
            {"id": 10, "summary": "A", "respondbydate": "2000-01-01T00:00:00"},
            # B: everything in the far future -> not overdue, excluded
            {
                "id": 11,
                "summary": "B",
                "respondbydate": "2999-01-01T00:00:00",
                "targetdate": "2999-01-01T00:00:00",
            },
            # C: fix/target deadline long past -> fix breach
            {"id": 12, "summary": "C", "targetdate": "2000-01-01T00:00:00"},
        ],
    }

    def responder(request: httpx.Request) -> httpx.Response:
        sink["params"] = dict(request.url.params)
        return httpx.Response(200, json=payload)

    respx_mock.get(api("Tickets")).mock(side_effect=responder)
    data = await call(make_settings(), "list_overdue_tickets", {})

    # overdue tools only consider open tickets
    assert sink["params"]["open_only"].lower() == "true"
    ids = {i["id"] for i in data["items"]}
    assert ids == {10, 12}
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id[10]["response_overdue"] is True and by_id[10]["fix_overdue"] is False
    assert by_id[12]["fix_overdue"] is True and by_id[12]["response_overdue"] is False
    assert data["count"] == 2


async def test_list_overdue_tickets_breach_filter_response_only(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    payload = {
        "record_count": 2,
        "tickets": [
            {"id": 10, "summary": "A", "respondbydate": "2000-01-01T00:00:00"},
            {"id": 12, "summary": "C", "targetdate": "2000-01-01T00:00:00"},
        ],
    }
    respx_mock.get(api("Tickets")).mock(return_value=httpx.Response(200, json=payload))
    data = await call(make_settings(), "list_overdue_tickets", {"breach": "response"})
    assert {i["id"] for i in data["items"]} == {10}


async def test_list_overdue_tickets_skips_sla_excluded(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    payload = {
        "record_count": 2,
        "tickets": [
            {"id": 10, "summary": "tracked", "respondbydate": "2000-01-01T00:00:00"},
            # Deadline long past but excluded from SLA -> must not be flagged.
            {
                "id": 99,
                "summary": "excluded",
                "respondbydate": "2000-01-01T00:00:00",
                "excludefromsla": True,
            },
        ],
    }
    respx_mock.get(api("Tickets")).mock(return_value=httpx.Response(200, json=payload))
    data = await call(make_settings(), "list_overdue_tickets", {})
    assert {i["id"] for i in data["items"]} == {10}
