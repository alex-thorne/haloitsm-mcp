"""Write tools (registered only when ``HALO_ENABLE_WRITES=true``).

Every write tool takes a required ``confirm`` flag and refuses unless it is
True — a server-side gate that holds for every client, regardless of harness.
When the host advertises elicitation, the tool additionally asks for an
interactive confirmation (capability-checked, with graceful fallback to the
``confirm`` flag).

Updates always carry an explicit ``id``: Halo upserts on POST, so an update
without ``id`` would silently create a duplicate (enforced by
:meth:`HaloClient.post_update`).
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from ..client import HaloAPIError, HaloClient
from ..models import (
    AssetSummary,
    ClientSummary,
    SiteSummary,
    TicketActionSummary,
    TicketSummary,
    UserSummary,
)
from ..observability import get_logger

_log = get_logger()


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def _supports_elicitation(ctx: Context) -> bool:
    """True when the connected client advertised the elicitation capability."""
    client_params = getattr(ctx.session, "client_params", None)
    capabilities = getattr(client_params, "capabilities", None)
    return getattr(capabilities, "elicitation", None) is not None


async def _gate(ctx: Context, confirm: bool, prompt: str) -> dict[str, Any] | None:
    """Return a refusal/cancel envelope, or None when the write may proceed."""
    if not confirm:
        return {
            "ok": False,
            "reason": "confirm_required",
            "message": "This write requires confirm=true.",
        }
    if _supports_elicitation(ctx):
        try:
            result = await ctx.elicit(prompt, response_type=bool)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - elicitation failure must fail closed, not proceed
            _log.warning(
                "elicitation failed; refusing the write (fail-closed)",
                extra={"path": "elicit"},
            )
            return {
                "ok": False,
                "reason": "elicitation_failed",
                "message": "Interactive confirmation could not be obtained; the write was refused.",
            }
        accepted = result.action == "accept" and bool(getattr(result, "data", False))
        if not accepted:
            return {
                "ok": False,
                "reason": "cancelled",
                "message": "The user did not confirm the write.",
            }
    return None


def _project_write(body: Any, model: type[Any]) -> Any:
    """Project a Halo write response (object, or single-element array) compactly."""
    if isinstance(body, list):
        body = body[0] if body else {}
    if isinstance(body, dict) and body.get("id") is not None:
        return model.project(body)
    return body


def _project_ticket_write(client: HaloClient, body: Any) -> Any:
    """Project a ticket write response and attach its portal deep link."""
    projected = _project_write(body, TicketSummary)
    if isinstance(projected, dict) and projected.get("id") is not None:
        projected["url"] = client.ticket_url(projected["id"])
    return projected


# Cap on tickets touched by a single bulk write, to bound accidental blast radius.
_MAX_BULK = 50


def _dedupe(ids: list[int]) -> list[int]:
    """Preserve order while dropping duplicate ids."""
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _bulk_guard(ids: list[int]) -> dict[str, Any] | None:
    """Refuse empty or oversized batches before any confirmation or write."""
    if not ids:
        return {
            "ok": False,
            "reason": "empty_batch",
            "message": "Provide at least one ticket id.",
        }
    if len(ids) > _MAX_BULK:
        return {
            "ok": False,
            "reason": "batch_too_large",
            "message": f"Batch of {len(ids)} exceeds the {_MAX_BULK}-ticket limit; split it up.",
        }
    return None


async def _bulk_apply(client: HaloClient, ids: list[int], fields: dict[str, Any]) -> dict[str, Any]:
    """Apply the same update to each id, collecting per-item results.

    A single failing ticket is recorded and the batch continues, so one bad id
    never sinks the rest. Each update carries an explicit id via post_update.
    """
    results: list[dict[str, Any]] = []
    succeeded = 0
    for ticket_id in ids:
        url = client.ticket_url(ticket_id)
        try:
            await client.post_update("/Tickets", {"id": ticket_id, **fields})
        except HaloAPIError as exc:
            results.append({"id": ticket_id, "url": url, "ok": False, "error": str(exc)})
            continue
        results.append({"id": ticket_id, "url": url, "ok": True})
        succeeded += 1
    return {
        "ok": succeeded == len(ids),
        "succeeded": succeeded,
        "failed": len(ids) - succeeded,
        "results": results,
    }


def register_write_tools(mcp: FastMCP, client: HaloClient) -> None:
    """Register the gated write tools on ``mcp``."""

    @mcp.tool
    async def create_ticket(
        summary: str,
        details: str,
        client_id: int,
        confirm: bool,
        ctx: Context,
        ticket_type: int | None = None,
        priority_id: int | None = None,
        agent_id: int | None = None,
        team_id: int | None = None,
        site_id: int | None = None,
        user_id: int | None = None,
        category_1: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Halo ticket. Requires confirm=true.

        Optionally set priority, assignment (agent_id/team_id), site, requester
        (user_id) and category. Resolve ids with the read lookup tools first.
        """
        prompt = f"Create a new ticket for client {client_id}: {summary!r}?"
        gate = await _gate(ctx, confirm, prompt)
        if gate is not None:
            return gate
        payload = _clean(
            {
                "summary": summary,
                "details": details,
                "client_id": client_id,
                "tickettype_id": ticket_type,
                "priority_id": priority_id,
                "agent_id": agent_id,
                "team_id": team_id,
                "site_id": site_id,
                "user_id": user_id,
                "category_1": category_1,
            }
        )
        created = await client.post("/Tickets", payload)
        return {"ok": True, "ticket": _project_ticket_write(client, created)}

    @mcp.tool
    async def update_ticket(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing ticket (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update ticket {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Tickets", {**fields, "id": id})
        return {"ok": True, "ticket": _project_ticket_write(client, updated)}

    @mcp.tool
    async def set_ticket_status(
        id: int, status_id: int, confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Set a ticket's status (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Set ticket {id} to status {status_id}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Tickets", {"id": id, "status_id": status_id})
        return {"ok": True, "ticket": _project_ticket_write(client, updated)}

    @mcp.tool
    async def assign_ticket(
        id: int,
        confirm: bool,
        ctx: Context,
        agent_id: int | None = None,
        team_id: int | None = None,
    ) -> dict[str, Any]:
        """Assign a ticket to an agent and/or team (id required). Requires confirm=true.

        Provide agent_id, team_id, or both. Resolve ids with list_agents /
        list_teams first.
        """
        if agent_id is None and team_id is None:
            return {
                "ok": False,
                "reason": "nothing_to_assign",
                "message": "Provide agent_id and/or team_id.",
            }
        gate = await _gate(ctx, confirm, f"Assign ticket {id} to agent={agent_id}, team={team_id}?")
        if gate is not None:
            return gate
        updated = await client.post_update(
            "/Tickets", _clean({"id": id, "agent_id": agent_id, "team_id": team_id})
        )
        return {"ok": True, "ticket": _project_ticket_write(client, updated)}

    @mcp.tool
    async def set_ticket_priority(
        id: int, priority_id: int, confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Set a ticket's priority (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Set ticket {id} to priority {priority_id}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Tickets", {"id": id, "priority_id": priority_id})
        return {"ok": True, "ticket": _project_ticket_write(client, updated)}

    @mcp.tool
    async def bulk_assign(
        ticket_ids: list[int],
        confirm: bool,
        ctx: Context,
        agent_id: int | None = None,
        team_id: int | None = None,
    ) -> dict[str, Any]:
        """Assign many tickets to an agent and/or team in one guarded batch.

        Requires confirm=true. Refuses when no agent_id/team_id is given, on an
        empty list, or on a batch larger than 50. Duplicate ids are collapsed and
        each ticket is updated by explicit id; per-ticket results are returned so
        partial failures are visible.
        """
        if agent_id is None and team_id is None:
            return {
                "ok": False,
                "reason": "nothing_to_assign",
                "message": "Provide agent_id and/or team_id.",
            }
        ids = _dedupe(ticket_ids)
        guard = _bulk_guard(ids)
        if guard is not None:
            return guard
        gate = await _gate(
            ctx, confirm, f"Assign {len(ids)} tickets to agent={agent_id}, team={team_id}?"
        )
        if gate is not None:
            return gate
        return await _bulk_apply(client, ids, _clean({"agent_id": agent_id, "team_id": team_id}))

    @mcp.tool
    async def bulk_set_status(
        ticket_ids: list[int], status_id: int, confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Set the status of many tickets in one guarded batch. Requires confirm=true.

        Refuses an empty list or a batch larger than 50. Duplicate ids are
        collapsed and each ticket is updated by explicit id; per-ticket results
        are returned.
        """
        ids = _dedupe(ticket_ids)
        guard = _bulk_guard(ids)
        if guard is not None:
            return guard
        gate = await _gate(ctx, confirm, f"Set {len(ids)} tickets to status {status_id}?")
        if gate is not None:
            return gate
        return await _bulk_apply(client, ids, {"status_id": status_id})

    @mcp.tool
    async def add_action(
        ticket_id: int,
        note: str,
        confirm: bool,
        ctx: Context,
        outcome: str | None = None,
        outcome_id: int | None = None,
        new_status: int | None = None,
        hidden_from_user: bool | None = None,
    ) -> dict[str, Any]:
        """Add an action (note/update) to a ticket. Requires confirm=true.

        Set hidden_from_user=true for a private, agent-only note; pass new_status
        to change the ticket's status as part of the same update.
        """
        gate = await _gate(ctx, confirm, f"Add an action to ticket {ticket_id}?")
        if gate is not None:
            return gate
        payload = _clean(
            {
                "ticket_id": ticket_id,
                "note": note,
                "outcome": outcome,
                "outcome_id": outcome_id,
                "new_status": new_status,
                "hiddenfromuser": hidden_from_user,
            }
        )
        created = await client.post("/Actions", payload)
        return {
            "ok": True,
            "action": _project_write(created, TicketActionSummary),
            "ticket_url": client.ticket_url(ticket_id),
        }

    @mcp.tool
    async def update_client(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing client (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update client {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Client", {**fields, "id": id})
        return {"ok": True, "client": _project_write(updated, ClientSummary)}

    @mcp.tool
    async def update_user(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing user (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update user {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Users", {**fields, "id": id})
        return {"ok": True, "user": _project_write(updated, UserSummary)}

    @mcp.tool
    async def create_site(name: str, client_id: int, confirm: bool, ctx: Context) -> dict[str, Any]:
        """Create a new site for a client. Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Create site {name!r} for client {client_id}?")
        if gate is not None:
            return gate
        created = await client.post("/Site", _clean({"name": name, "client_id": client_id}))
        return {"ok": True, "site": _project_write(created, SiteSummary)}

    @mcp.tool
    async def update_site(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing site (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update site {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Site", {**fields, "id": id})
        return {"ok": True, "site": _project_write(updated, SiteSummary)}

    @mcp.tool
    async def create_asset(
        inventory_number: str, client_id: int, confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Create a new asset / configuration item. Requires confirm=true."""
        gate = await _gate(
            ctx, confirm, f"Create asset {inventory_number!r} for client {client_id}?"
        )
        if gate is not None:
            return gate
        created = await client.post(
            "/Asset", _clean({"inventory_number": inventory_number, "client_id": client_id})
        )
        return {"ok": True, "asset": _project_write(created, AssetSummary)}

    @mcp.tool
    async def update_asset(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing asset (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update asset {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Asset", {**fields, "id": id})
        return {"ok": True, "asset": _project_write(updated, AssetSummary)}
