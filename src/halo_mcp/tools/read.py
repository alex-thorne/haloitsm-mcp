"""Read tools (always registered).

Each tool returns a compact projection (see :mod:`halo_mcp.models`) rather than
the raw Halo blob, to keep tool output small. List tools fetch a single page
(``page`` / ``page_size``) and return ``{record_count, page, items}``.

The data-fetching helpers (:func:`fetch_page`, :func:`whoami_query`) are shared
with the smoke test so it exercises the exact same code path.
"""

from __future__ import annotations

import collections
from datetime import datetime
from typing import Any

from fastmcp import FastMCP

from ..client import HALO_MAX_PAGE_SIZE, HaloClient, HaloForbiddenError
from ..models import (
    AgentSummary,
    AppointmentSummary,
    AssetSummary,
    AttachmentSummary,
    CategorySummary,
    ClientSummary,
    InvoiceSummary,
    ItemSummary,
    OpportunitySummary,
    PrioritySummary,
    ProjectSummary,
    ReportSummary,
    SiteSummary,
    SlaSummary,
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


# Ticket dimensions summarise_tickets can group by. Limited to fields the Halo
# *list* view reliably returns (priority_name/slaresponsestate come only from a
# single-ticket fetch, so grouping on them over list data would be all-None).
_ALLOWED_GROUP_BY = frozenset(
    {
        "status_id",
        "tickettype_id",
        "priority_id",
        "team",
        "team_id",
        "agent_id",
        "client_id",
        "client_name",
        "site_name",
        "category_1",
    }
)
_BREACH_MODES = frozenset({"any", "response", "fix"})


def _ticket_params(
    *,
    status: int | None = None,
    client_id: int | None = None,
    agent_id: int | None = None,
    team: str | None = None,
    search: str | None = None,
    created_since: str | None = None,
    created_before: str | None = None,
    open_only: bool = False,
) -> dict[str, Any]:
    """Build the Halo /Tickets query params shared by the list/analytics tools."""
    # Only name the date field when a bound is given, so unfiltered calls send no
    # date params at all.
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
    if open_only:
        params["open_only"] = True
    return params


def _parse_dt(value: Any) -> datetime | None:
    """Parse a Halo ISO-8601 date string, or None if absent/unparseable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return None


def _age_days(rows: list[dict[str, Any]], now: datetime) -> dict[str, int] | None:
    """Descriptive age stats (days since dateoccurred) over projected rows."""
    ages = sorted(
        (now - d).days for d in (_parse_dt(r.get("dateoccurred")) for r in rows) if d is not None
    )
    if not ages:
        return None
    return {
        "min": ages[0],
        "median": ages[len(ages) // 2],
        "max": ages[-1],
        "mean": round(sum(ages) / len(ages)),
    }


def register_read_tools(mcp: FastMCP, client: HaloClient) -> None:
    """Register the always-on read tools on ``mcp``."""

    @mcp.tool
    async def list_tickets(
        status: int | None = None,
        client_id: int | None = None,
        agent_id: int | None = None,
        team: str | None = None,
        search: str | None = None,
        open_only: bool = False,
        created_since: str | None = None,
        created_before: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """List Halo tickets, filtered by status, client, agent, team, free text,
        creation date, or open_only.

        ``open_only=true`` returns just the open backlog; by default Halo returns
        open plus recently-closed tickets. ``created_since`` / ``created_before``
        take an ISO-8601 date or datetime (e.g. ``2026-06-16`` or
        ``2026-06-16T00:00:00``) and filter on the ticket's logged date (Halo
        ``dateoccurred``), server-side.
        """
        params = _ticket_params(
            status=status,
            client_id=client_id,
            agent_id=agent_id,
            team=team,
            search=search,
            created_since=created_since,
            created_before=created_before,
            open_only=open_only,
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
    async def summarise_tickets(
        group_by: str = "status_id",
        status: int | None = None,
        client_id: int | None = None,
        agent_id: int | None = None,
        team: str | None = None,
        open_only: bool = False,
        created_since: str | None = None,
        created_before: str | None = None,
        max_records: int = 5000,
    ) -> dict[str, Any]:
        """Aggregate tickets into counts by one dimension, with backlog age stats.

        ``group_by`` is one of: status_id, tickettype_id, priority_id,
        priority_name, team, team_id, agent_id, client_id, client_name,
        slaresponsestate, site_name, category_1. Walks every matching page (up to
        ``max_records``) and returns ``{total, group_by, groups, age_days}``.
        Resolve ids to names with the matching lookup tool (list_statuses,
        list_priorities, list_agents, …).
        """
        if group_by not in _ALLOWED_GROUP_BY:
            return {
                "error": "invalid_group_by",
                "message": "group_by must be one of the supported ticket dimensions.",
                "allowed": sorted(_ALLOWED_GROUP_BY),
            }
        params = _ticket_params(
            status=status,
            client_id=client_id,
            agent_id=agent_id,
            team=team,
            created_since=created_since,
            created_before=created_before,
            open_only=open_only,
        )
        try:
            raw = await client.paginate(
                "/Tickets", collection_key="tickets", params=params, max_records=max_records
            )
        except HaloForbiddenError as exc:
            return _scope_error(client, exc)
        rows = TicketSummary.project_many(raw)
        counts = collections.Counter(
            r.get(group_by) if r.get(group_by) not in (None, "") else None for r in rows
        )
        groups = [{"value": value, "count": count} for value, count in counts.most_common()]
        return {
            "total": len(rows),
            "group_by": group_by,
            "groups": groups,
            "age_days": _age_days(rows, datetime.now()),
        }

    @mcp.tool
    async def list_overdue_tickets(
        breach: str = "any",
        team: str | None = None,
        client_id: int | None = None,
        agent_id: int | None = None,
        max_records: int = 2000,
    ) -> dict[str, Any]:
        """List OPEN tickets past an SLA deadline, most overdue first.

        ``response_overdue`` = the first-response deadline (respondbydate) has
        passed with no first response logged in time (responsedate missing or
        later than the deadline). ``fix_overdue`` = the fix-by / target deadline
        has passed. Tickets flagged ``excludefromsla`` are skipped and Halo's
        1899/1900 "unset" dates count as no deadline. ``breach`` selects which to
        check: "response", "fix", or "any" (default).
        """
        if breach not in _BREACH_MODES:
            return {
                "error": "invalid_breach",
                "message": "breach must be one of: any, response, fix.",
                "allowed": sorted(_BREACH_MODES),
            }
        params = _ticket_params(team=team, client_id=client_id, agent_id=agent_id, open_only=True)
        try:
            raw = await client.paginate(
                "/Tickets", collection_key="tickets", params=params, max_records=max_records
            )
        except HaloForbiddenError as exc:
            return _scope_error(client, exc)
        now = datetime.now()
        items: list[dict[str, Any]] = []
        for r in TicketSummary.project_many(raw):
            if r.get("excludefromsla"):
                continue
            respond_by = _parse_dt(r.get("respondbydate"))
            responded = _parse_dt(r.get("responsedate"))
            fix_by = _parse_dt(r.get("targetdate")) or _parse_dt(r.get("fixbydate"))
            response_overdue = bool(
                respond_by and respond_by < now and (responded is None or responded > respond_by)
            )
            fix_overdue = bool(fix_by and fix_by < now)
            if breach == "response" and not response_overdue:
                continue
            if breach == "fix" and not fix_overdue:
                continue
            if breach == "any" and not (response_overdue or fix_overdue):
                continue
            occurred = _parse_dt(r.get("dateoccurred"))
            items.append(
                {
                    "id": r["id"],
                    "summary": r.get("summary"),
                    "status_id": r.get("status_id"),
                    "priority_id": r.get("priority_id"),
                    "team": r.get("team"),
                    "agent_id": r.get("agent_id"),
                    "client_name": r.get("client_name"),
                    "onhold": r.get("onhold"),
                    "respondbydate": r.get("respondbydate"),
                    "responsedate": r.get("responsedate"),
                    "targetdate": r.get("targetdate"),
                    "response_overdue": response_overdue,
                    "fix_overdue": fix_overdue,
                    "age_days": (now - occurred).days if occurred else None,
                }
            )
        items.sort(key=lambda i: i["age_days"] if i["age_days"] is not None else -1, reverse=True)
        return {
            "now": now.isoformat(timespec="seconds"),
            "breach": breach,
            "count": len(items),
            "items": items,
        }

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
    async def list_priorities() -> dict[str, Any]:
        """List priorities with their SLA response/fix targets (lookup, resolves priority_id)."""
        return await fetch_page(
            client, "/Priority", collection_key="priorities", model=PrioritySummary
        )

    @mcp.tool
    async def list_slas() -> dict[str, Any]:
        """List SLAs and their working-hours calendar (lookup, resolves sla_id)."""
        return await fetch_page(client, "/Sla", collection_key="slas", model=SlaSummary)

    @mcp.tool
    async def list_categories() -> dict[str, Any]:
        """List ITIL categories (lookup, resolves category ids and request types)."""
        return await fetch_page(
            client, "/Category", collection_key="categories", model=CategorySummary
        )

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
