"""Read tools driven through an in-memory FastMCP client against respx mocks."""

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


async def test_list_tickets_projects_and_passes_filters(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    payload = {
        "record_count": 2,
        "tickets": [
            {"id": 1, "summary": "a", "status_id": 1, "details": "BIG", "extra": 9},
            {"id": 2, "summary": "b"},
        ],
    }
    respx_mock.get(api("Tickets")).mock(side_effect=capturing(payload, sink))

    data = await call(
        make_settings(),
        "list_tickets",
        {"status": 1, "client_id": 7, "search": "vpn", "page": 1, "page_size": 25},
    )

    assert data["record_count"] == 2
    assert [t["id"] for t in data["items"]] == [1, 2]
    assert "details" not in data["items"][0] and "extra" not in data["items"][0]
    assert sink["params"]["status_id"] == "1"
    assert sink["params"]["client_id"] == "7"
    assert sink["params"]["search"] == "vpn"
    assert sink["params"]["page_no"] == "1"
    assert sink["params"]["page_size"] == "25"


async def test_list_tickets_defaults_page_size_from_settings(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Tickets")).mock(
        side_effect=capturing({"record_count": 0, "tickets": []}, sink)
    )
    await call(make_settings(page_size=33), "list_tickets", {})
    assert sink["params"]["page_size"] == "33"


async def test_get_ticket_without_actions(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Tickets/55")).mock(
        return_value=httpx.Response(200, json={"id": 55, "summary": "down", "details": "BIG"})
    )
    data = await call(make_settings(), "get_ticket", {"id": 55})
    assert data["id"] == 55 and data["summary"] == "down"
    assert "details" not in data
    assert "actions" not in data


async def test_get_ticket_with_actions(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Tickets/55")).mock(
        return_value=httpx.Response(200, json={"id": 55, "summary": "down"})
    )
    actions_sink: dict[str, Any] = {}
    respx_mock.get(api("Actions")).mock(
        side_effect=capturing(
            {"actions": [{"id": 1, "ticket_id": 55, "note": "looking"}]}, actions_sink
        )
    )
    data = await call(make_settings(), "get_ticket", {"id": 55, "include_actions": True})
    assert data["id"] == 55
    assert [a["id"] for a in data["actions"]] == [1]
    assert actions_sink["params"]["ticket_id"] == "55"


async def test_search_tickets(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Tickets")).mock(
        side_effect=capturing({"record_count": 1, "tickets": [{"id": 9}]}, sink)
    )
    data = await call(make_settings(), "search_tickets", {"query": "outlook crash"})
    assert [t["id"] for t in data["items"]] == [9]
    assert sink["params"]["search"] == "outlook crash"


async def test_list_ticket_actions(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Actions")).mock(
        side_effect=capturing(
            {"record_count": 1, "actions": [{"id": 3, "ticket_id": 8, "outcome": "Note"}]}, sink
        )
    )
    data = await call(make_settings(), "list_ticket_actions", {"ticket_id": 8})
    assert [a["id"] for a in data["items"]] == [3]
    assert sink["params"]["ticket_id"] == "8"


async def test_list_assets_and_get_asset(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Asset")).mock(
        return_value=httpx.Response(
            200, json={"record_count": 1, "assets": [{"id": 2, "inventory_number": "PC-1"}]}
        )
    )
    respx_mock.get(api("Asset/2")).mock(
        return_value=httpx.Response(200, json={"id": 2, "inventory_number": "PC-1", "junk": 1})
    )
    listing = await call(make_settings(), "list_assets", {"client_id": 4})
    assert [a["id"] for a in listing["items"]] == [2]
    one = await call(make_settings(), "get_asset", {"id": 2})
    assert one["id"] == 2 and "junk" not in one


async def test_list_clients_users_agents_teams_statuses(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    respx_mock.get(api("Client")).mock(
        return_value=httpx.Response(200, json={"clients": [{"id": 1, "name": "Acme"}]})
    )
    respx_mock.get(api("Users")).mock(
        return_value=httpx.Response(200, json={"users": [{"id": 1, "name": "Sam"}]})
    )
    # Halo's /Agent returns a bare array (no wrapper) — must still normalise.
    respx_mock.get(api("Agent")).mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "Tech", "email": "t@x"}])
    )
    respx_mock.get(api("Team")).mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "1st Line"}])
    )
    respx_mock.get(api("Status")).mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "New"}])
    )
    s = make_settings()
    assert [c["id"] for c in (await call(s, "list_clients", {}))["items"]] == [1]
    assert [u["id"] for u in (await call(s, "list_users", {}))["items"]] == [1]
    assert [a["id"] for a in (await call(s, "list_agents", {}))["items"]] == [1]
    assert [t["id"] for t in (await call(s, "list_teams", {}))["items"]] == [1]
    assert [st["id"] for st in (await call(s, "list_statuses", {}))["items"]] == [1]


async def test_whoami_is_authenticated_probe(
    make_settings: Callable[..., Settings],
    respx_mock,
    mock_token,  # noqa: ANN001
) -> None:
    mock_token()
    sink: dict[str, Any] = {}
    respx_mock.get(api("Tickets")).mock(
        side_effect=capturing({"record_count": 123, "tickets": [{"id": 1}]}, sink)
    )
    data = await call(make_settings(), "whoami", {})
    assert data["authenticated"] is True
    assert data["ticket_record_count"] == 123
    assert sink["params"]["page_size"] == "1"
