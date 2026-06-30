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

from ..client import HaloClient
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
    ) -> dict[str, Any]:
        """Create a new Halo ticket. Requires confirm=true."""
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
            }
        )
        created = await client.post("/Tickets", payload)
        return {"ok": True, "ticket": _project_write(created, TicketSummary)}

    @mcp.tool
    async def update_ticket(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing ticket (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update ticket {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Tickets", {"id": id, **fields})
        return {"ok": True, "ticket": _project_write(updated, TicketSummary)}

    @mcp.tool
    async def set_ticket_status(
        id: int, status_id: int, confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Set a ticket's status (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Set ticket {id} to status {status_id}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Tickets", {"id": id, "status_id": status_id})
        return {"ok": True, "ticket": _project_write(updated, TicketSummary)}

    @mcp.tool
    async def add_action(
        ticket_id: int,
        note: str,
        confirm: bool,
        ctx: Context,
        outcome: str | None = None,
    ) -> dict[str, Any]:
        """Add an action (note/update) to a ticket. Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Add an action to ticket {ticket_id}?")
        if gate is not None:
            return gate
        payload = _clean({"ticket_id": ticket_id, "note": note, "outcome": outcome})
        created = await client.post("/Actions", payload)
        return {"ok": True, "action": _project_write(created, TicketActionSummary)}

    @mcp.tool
    async def update_client(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing client (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update client {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Client", {"id": id, **fields})
        return {"ok": True, "client": _project_write(updated, ClientSummary)}

    @mcp.tool
    async def update_user(
        id: int, fields: dict[str, Any], confirm: bool, ctx: Context
    ) -> dict[str, Any]:
        """Update fields on an existing user (id required). Requires confirm=true."""
        gate = await _gate(ctx, confirm, f"Update user {id} with {sorted(fields)}?")
        if gate is not None:
            return gate
        updated = await client.post_update("/Users", {"id": id, **fields})
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
        updated = await client.post_update("/Site", {"id": id, **fields})
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
        updated = await client.post_update("/Asset", {"id": id, **fields})
        return {"ok": True, "asset": _project_write(updated, AssetSummary)}
