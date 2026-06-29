"""Read-only smoke test: prove end-to-end connectivity to the Halo instance.

Performs the client-credentials token exchange, runs the ``whoami`` health
check, then fetches the first page of tickets and prints the record count and
the first few ids/summaries. Exits non-zero on any failure. Never writes.
"""

from __future__ import annotations

import asyncio
import sys

from pydantic import ValidationError

from .auth import HaloAuthError
from .client import HaloAPIError, HaloClient
from .config import Settings, load_settings
from .models import TicketSummary
from .tools.read import fetch_page, whoami_query


async def run_smoke(settings: Settings | None = None) -> int:
    """Return 0 on success, 1 on any configuration/auth/API failure."""
    try:
        settings = settings or load_settings()
    except ValidationError as exc:
        # Print only the offending field names — never the raw error, whose str
        # echoes the input dict (which would leak the client secret).
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors() if error.get("loc"))
        print(
            f"Configuration error — check your .env (missing/invalid: {fields})",
            file=sys.stderr,
        )
        return 1

    async with HaloClient(settings) as client:
        try:
            identity = await whoami_query(client)
            page = await fetch_page(
                client,
                "/Tickets",
                collection_key="tickets",
                model=TicketSummary,
                page=1,
                page_size=5,
            )
        except (HaloAuthError, HaloAPIError) as exc:
            print(f"Smoke test FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    print("Auth OK." if identity.get("authenticated") else "Auth FAILED.")
    print(f"Ticket record_count: {page['record_count']}")
    print("First page of tickets:")
    for ticket in page["items"][:5]:
        print(f"  #{ticket['id']}: {ticket.get('summary')}")
    return 0


def main() -> None:
    """Console-script entry point for ``halo-mcp-smoke``."""
    raise SystemExit(asyncio.run(run_smoke()))
