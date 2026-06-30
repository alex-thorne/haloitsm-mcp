"""FastMCP server assembly and entry point.

Read tools are always registered. Write tools are registered only when
``HALO_ENABLE_WRITES=true``. The default transport is stdio.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .client import HaloClient
from .config import Settings, load_settings
from .tools.read import register_read_tools

INSTRUCTIONS = """\
Halo ITSM tools wrap a Halo IT Service Management instance over its REST API.

Read tools (always available):
- list_tickets / search_tickets / get_ticket — find and inspect tickets; filter
  by status, client, agent, team, free text, or creation date (created_since /
  created_before).
- list_ticket_actions, or get_ticket(include_actions=true) — the updates/notes
  recorded on a ticket.
- list_assets / get_asset — configuration items and hardware.
- list_clients, list_users, list_agents, list_teams, list_statuses — directory
  and lookup data. Use list_statuses / list_teams to resolve names to ids before
  filtering or writing.
- whoami — quick authenticated health check.
- list_sites / get_site, list_suppliers / get_supplier, list_ticket_types —
  more directory and lookup data.
- list_projects / get_project, list_opportunities / get_opportunity — delivery
  and sales records.
- list_invoices / get_invoice, list_items / get_item — billing and catalogue.
- list_appointments / get_appointment, list_attachments (by ticket),
  list_reports — scheduling, attachment metadata, and the report catalogue.

Results are compact projections (ids + key fields), not full Halo records. List
tools return {record_count, page, items}; page with page / page_size.

Write tools (create_ticket, update_ticket, add_action, set_ticket_status) exist
only when the operator has enabled writes. They require confirm=true and, on
hosts that support it, an interactive confirmation. Updates always carry the
record id — Halo upserts on POST, so omitting the id creates a duplicate.
"""


def build_server(settings: Settings | None = None) -> FastMCP:
    """Construct the FastMCP server with the appropriate tool surface."""
    settings = settings or load_settings()
    client = HaloClient(settings)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await client.aclose()

    mcp: FastMCP = FastMCP("halo-itsm", instructions=INSTRUCTIONS, lifespan=lifespan)
    register_read_tools(mcp, client)
    if settings.enable_writes:
        # Imported lazily so the write surface is absent unless explicitly enabled.
        from .tools.write import register_write_tools

        register_write_tools(mcp, client)
    return mcp


def main() -> None:
    """Console-script entry point: serve over stdio."""
    from .config import load_settings
    from .observability import configure_logging

    settings = load_settings()
    configure_logging(settings.log_level, settings.log_format)
    build_server(settings).run()
