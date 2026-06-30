"""Read tools (always registered).

Each tool returns a compact projection (see :mod:`halo_mcp.models`) rather than
the raw Halo blob, to keep tool output small. List tools fetch a single page
(``page`` / ``page_size``) and return ``{record_count, page, items}``.

The data-fetching helpers (:func:`fetch_page`, :func:`whoami_query`) are shared
with the smoke test so it exercises the exact same code path.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import HaloClient
from ..models import (
    AgentSummary,
    AssetSummary,
    ClientSummary,
    StatusSummary,
    TeamSummary,
    TicketActionSummary,
    TicketSummary,
    UserSummary,
)


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None so we never send empty query params."""
    return {k: v for k, v in params.items() if v is not None}


async def fetch_page(
    client: HaloClient,
    resource: str,
    *,
    collection_key: str,
    model: type[Any],
    params: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Fetch one Halo list page and return a compact ``{record_count, page, items}``.

    Tolerates both wrapped responses (``{collection_key: [...], record_count}``)
    and bare arrays (e.g. ``/Agent``).
    """
    size = page_size or client.page_size
    query = {**_clean(params or {}), "pageinate": True, "page_no": page, "page_size": size}
    body = await client.get(resource, params=query, timeout=timeout)
    if isinstance(body, list):
        rows, record_count = body, None
    elif isinstance(body, dict):
        rows = body.get(collection_key) or []
        rc = body.get("record_count")
        record_count = rc if isinstance(rc, int) else None
    else:
        rows, record_count = [], None
    return {"record_count": record_count, "page": page, "items": model.project_many(rows)}


async def whoami_query(client: HaloClient) -> dict[str, Any]:
    """Lightweight authenticated probe used by the smoke test and health checks."""
    body = await client.get("/Tickets", params={"pageinate": True, "page_no": 1, "page_size": 1})
    record_count = body.get("record_count") if isinstance(body, dict) else None
    return {"authenticated": True, "ticket_record_count": record_count}


def register_read_tools(mcp: FastMCP, client: HaloClient) -> None:
    """Register the always-on read tools on ``mcp``."""

    @mcp.tool
    async def list_tickets(
        status: int | None = None,
        client_id: int | None = None,
        agent_id: int | None = None,
        team: str | None = None,
        search: str | None = None,
        created_since: str | None = None,
        created_before: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """List Halo tickets, filtered by status, client, agent, team, free text or creation date.

        ``created_since`` / ``created_before`` take an ISO-8601 date or datetime
        (e.g. ``2026-06-16`` or ``2026-06-16T00:00:00``) and filter on the
        ticket's logged date (Halo ``dateoccurred``), server-side.
        """
        # Only name the date field when a bound is given, so unfiltered calls
        # send no date params at all.
        date_field = "dateoccurred" if (created_since or created_before) else None
        params = _clean(
            {
                "status_id": status,
                "client_id": client_id,
                "agent_id": agent_id,
                "team": team,
                "search": search,
                "datesearch": date_field,
                "startdate": created_since,
                "enddate": created_before,
            }
        )
        return await fetch_page(
            client,
            "/Tickets",
            collection_key="tickets",
            model=TicketSummary,
            params=params,
            page=page,
            page_size=page_size,
        )

    @mcp.tool
    async def get_ticket(id: int, include_actions: bool = False) -> dict[str, Any]:
        """Get a single ticket by id; set include_actions to also return its actions."""
        body = await client.get(f"/Tickets/{id}")
        ticket = TicketSummary.project(body) if isinstance(body, dict) else {}
        if include_actions:
            actions = await fetch_page(
                client,
                "/Actions",
                collection_key="actions",
                model=TicketActionSummary,
                params={"ticket_id": id},
            )
            ticket["actions"] = actions["items"]
        return ticket

    @mcp.tool
    async def search_tickets(query: str, page: int = 1) -> dict[str, Any]:
        """Free-text search across tickets."""
        return await fetch_page(
            client,
            "/Tickets",
            collection_key="tickets",
            model=TicketSummary,
            params={"search": query},
            page=page,
        )

    @mcp.tool
    async def list_ticket_actions(ticket_id: int, page: int = 1) -> dict[str, Any]:
        """List the actions (updates/notes) recorded against a ticket."""
        return await fetch_page(
            client,
            "/Actions",
            collection_key="actions",
            model=TicketActionSummary,
            params={"ticket_id": ticket_id},
            page=page,
        )

    @mcp.tool
    async def list_assets(
        client_id: int | None = None, search: str | None = None, page: int = 1
    ) -> dict[str, Any]:
        """List configuration items / assets, optionally filtered by client or free text."""
        return await fetch_page(
            client,
            "/Asset",
            collection_key="assets",
            model=AssetSummary,
            params=_clean({"client_id": client_id, "search": search}),
            page=page,
        )

    @mcp.tool
    async def get_asset(id: int) -> dict[str, Any]:
        """Get a single asset by id."""
        body = await client.get(f"/Asset/{id}")
        return AssetSummary.project(body) if isinstance(body, dict) else {}

    @mcp.tool
    async def list_clients(search: str | None = None, page: int = 1) -> dict[str, Any]:
        """List customers/clients, optionally filtered by free text."""
        return await fetch_page(
            client,
            "/Client",
            collection_key="clients",
            model=ClientSummary,
            params=_clean({"search": search}),
            page=page,
        )

    @mcp.tool
    async def list_users(
        client_id: int | None = None, search: str | None = None, page: int = 1
    ) -> dict[str, Any]:
        """List end users, optionally filtered by client or free text."""
        return await fetch_page(
            client,
            "/Users",
            collection_key="users",
            model=UserSummary,
            params=_clean({"client_id": client_id, "search": search}),
            page=page,
        )

    @mcp.tool
    async def list_agents(search: str | None = None, page: int = 1) -> dict[str, Any]:
        """List Halo agents (technicians), optionally filtered by free text."""
        return await fetch_page(
            client,
            "/Agent",
            collection_key="agents",
            model=AgentSummary,
            params=_clean({"search": search}),
            page=page,
        )

    @mcp.tool
    async def list_teams() -> dict[str, Any]:
        """List agent teams (lookup, for resolving team names to ids)."""
        return await fetch_page(client, "/Team", collection_key="teams", model=TeamSummary)

    @mcp.tool
    async def list_statuses() -> dict[str, Any]:
        """List ticket statuses (lookup, for resolving status names to ids)."""
        return await fetch_page(client, "/Status", collection_key="statuses", model=StatusSummary)

    @mcp.tool
    async def whoami() -> dict[str, Any]:
        """Lightweight authenticated health check; proves the token reaches Halo."""
        return await whoami_query(client)
