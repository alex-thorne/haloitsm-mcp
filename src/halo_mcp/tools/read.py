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

from ..client import HALO_MAX_PAGE_SIZE, HaloClient, HaloForbiddenError
from ..models import (
    AgentSummary,
    AppointmentSummary,
    AssetSummary,
    AttachmentSummary,
    ClientSummary,
    InvoiceSummary,
    ItemSummary,
    OpportunitySummary,
    ProjectSummary,
    ReportSummary,
    SiteSummary,
    StatusSummary,
    SupplierSummary,
    TeamSummary,
    TicketActionSummary,
    TicketSummary,
    TicketTypeSummary,
    UserSummary,
)


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None so we never send empty query params."""
    return {k: v for k, v in params.items() if v is not None}


def _scope_error(client: HaloClient, exc: HaloForbiddenError) -> dict[str, Any]:
    """Turn a 403 into a compact, actionable envelope instead of a raw error.

    The resource is outside the granted OAuth scopes; name the path and the
    scopes we hold (non-secret) so the operator knows what to widen.
    """
    return {
        "error": "insufficient_scope",
        "message": (
            "Halo returned 403 Forbidden for this resource. The granted OAuth scopes "
            "likely do not cover it — widen HALO_SCOPES (and the Halo application's "
            "permissions), then reload the server."
        ),
        "path": exc.path,
        "granted_scopes": client.scopes,
    }


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
    and bare arrays (e.g. ``/Agent``). ``page_size`` is clamped to Halo's 100-row
    cap. A 403 is returned as an ``insufficient_scope`` envelope, not raised.
    """
    size = min(page_size or client.page_size, HALO_MAX_PAGE_SIZE)
    query = {**_clean(params or {}), "pageinate": True, "page_no": page, "page_size": size}
    try:
        body = await client.get(resource, params=query, timeout=timeout)
    except HaloForbiddenError as exc:
        return _scope_error(client, exc)
    if isinstance(body, list):
        rows: list[Any] = body
        record_count = None
    elif isinstance(body, dict):
        found = body.get(collection_key)
        # Halo's envelope key varies per endpoint (e.g. /Agent -> "results"); fall
        # back to the first list-valued field rather than returning nothing.
        rows = (
            found
            if isinstance(found, list)
            else next((v for v in body.values() if isinstance(v, list)), [])
        )
        rc = body.get("record_count")
        record_count = rc if isinstance(rc, int) else None
    else:
        rows, record_count = [], None
    return {"record_count": record_count, "page": page, "items": model.project_many(rows)}


async def fetch_one(
    client: HaloClient, resource: str, id: int, *, model: type[Any]
) -> dict[str, Any]:
    """Fetch a single Halo record by id and return its compact projection."""
    try:
        body = await client.get(f"/{resource}/{id}")
    except HaloForbiddenError as exc:
        return _scope_error(client, exc)
    return model.project(body) if isinstance(body, dict) else {}


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
            collection_key="results",
            model=AgentSummary,
            params=_clean({"search": search}),
            page=page,
        )

    @mcp.tool
    async def get_agent(id: int) -> dict[str, Any]:
        """Get a single Halo agent (technician) by id."""
        return await fetch_one(client, "Agent", id, model=AgentSummary)

    @mcp.tool
    async def list_teams() -> dict[str, Any]:
        """List agent teams (lookup, for resolving team names to ids)."""
        return await fetch_page(client, "/Team", collection_key="teams", model=TeamSummary)

    @mcp.tool
    async def list_statuses() -> dict[str, Any]:
        """List ticket statuses (lookup, for resolving status names to ids)."""
        return await fetch_page(client, "/Status", collection_key="statuses", model=StatusSummary)

    @mcp.tool
    async def list_sites(
        client_id: int | None = None, search: str | None = None, page: int = 1
    ) -> dict[str, Any]:
        """List sites/locations, optionally filtered by client or free text."""
        return await fetch_page(
            client,
            "/Site",
            collection_key="sites",
            model=SiteSummary,
            params=_clean({"client_id": client_id, "search": search}),
            page=page,
        )

    @mcp.tool
    async def get_site(id: int) -> dict[str, Any]:
        """Get a single site by id."""
        return await fetch_one(client, "Site", id, model=SiteSummary)

    @mcp.tool
    async def list_suppliers(search: str | None = None, page: int = 1) -> dict[str, Any]:
        """List suppliers, optionally filtered by free text."""
        return await fetch_page(
            client,
            "/Supplier",
            collection_key="suppliers",
            model=SupplierSummary,
            params=_clean({"search": search}),
            page=page,
        )

    @mcp.tool
    async def get_supplier(id: int) -> dict[str, Any]:
        """Get a single supplier by id."""
        return await fetch_one(client, "Supplier", id, model=SupplierSummary)

    @mcp.tool
    async def list_ticket_types() -> dict[str, Any]:
        """List ticket types (lookup, for resolving type names to ids)."""
        return await fetch_page(
            client, "/TicketType", collection_key="tickettypes", model=TicketTypeSummary
        )

    @mcp.tool
    async def list_projects(
        client_id: int | None = None, search: str | None = None, page: int = 1
    ) -> dict[str, Any]:
        """List projects, optionally filtered by client or free text."""
        return await fetch_page(
            client,
            "/Projects",
            collection_key="projects",
            model=ProjectSummary,
            params=_clean({"client_id": client_id, "search": search}),
            page=page,
        )

    @mcp.tool
    async def get_project(id: int) -> dict[str, Any]:
        """Get a single project by id."""
        return await fetch_one(client, "Projects", id, model=ProjectSummary)

    @mcp.tool
    async def list_opportunities(
        client_id: int | None = None, search: str | None = None, page: int = 1
    ) -> dict[str, Any]:
        """List sales opportunities, optionally filtered by client or free text."""
        return await fetch_page(
            client,
            "/Opportunities",
            collection_key="opportunities",
            model=OpportunitySummary,
            params=_clean({"client_id": client_id, "search": search}),
            page=page,
        )

    @mcp.tool
    async def get_opportunity(id: int) -> dict[str, Any]:
        """Get a single opportunity by id."""
        return await fetch_one(client, "Opportunities", id, model=OpportunitySummary)

    @mcp.tool
    async def list_invoices(client_id: int | None = None, page: int = 1) -> dict[str, Any]:
        """List invoices, optionally filtered by client."""
        return await fetch_page(
            client,
            "/Invoice",
            collection_key="invoices",
            model=InvoiceSummary,
            params=_clean({"client_id": client_id}),
            page=page,
        )

    @mcp.tool
    async def get_invoice(id: int) -> dict[str, Any]:
        """Get a single invoice by id."""
        return await fetch_one(client, "Invoice", id, model=InvoiceSummary)

    @mcp.tool
    async def list_items(search: str | None = None, page: int = 1) -> dict[str, Any]:
        """List catalogue items, optionally filtered by free text."""
        return await fetch_page(
            client,
            "/Item",
            collection_key="items",
            model=ItemSummary,
            params=_clean({"search": search}),
            page=page,
        )

    @mcp.tool
    async def get_item(id: int) -> dict[str, Any]:
        """Get a single catalogue item by id."""
        return await fetch_one(client, "Item", id, model=ItemSummary)

    @mcp.tool
    async def list_appointments(agent_id: int | None = None, page: int = 1) -> dict[str, Any]:
        """List appointments, optionally filtered by agent."""
        return await fetch_page(
            client,
            "/Appointment",
            collection_key="appointments",
            model=AppointmentSummary,
            params=_clean({"agent_id": agent_id}),
            page=page,
        )

    @mcp.tool
    async def get_appointment(id: int) -> dict[str, Any]:
        """Get a single appointment by id."""
        return await fetch_one(client, "Appointment", id, model=AppointmentSummary)

    @mcp.tool
    async def list_attachments(ticket_id: int, page: int = 1) -> dict[str, Any]:
        """List attachment metadata for a ticket (no binary download)."""
        return await fetch_page(
            client,
            "/Attachment",
            collection_key="attachments",
            model=AttachmentSummary,
            params={"ticket_id": ticket_id},
            page=page,
        )

    @mcp.tool
    async def list_reports(page: int = 1) -> dict[str, Any]:
        """List available reports (lookup). Uses the longer report timeout."""
        return await fetch_page(
            client,
            "/Report",
            collection_key="reports",
            model=ReportSummary,
            page=page,
            timeout=client.long_timeout,
        )

    @mcp.tool
    async def whoami() -> dict[str, Any]:
        """Lightweight authenticated health check; proves the token reaches Halo."""
        return await whoami_query(client)
