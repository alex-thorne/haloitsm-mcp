"""Request logging is structured, carries no secrets, and uses stderr."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any

import httpx

from halo_mcp.client import HaloClient
from halo_mcp.config import Settings


class RecordingHTTP:
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        json: Any = None,
        headers: Any = None,
        timeout: Any = None,
    ) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async def aclose(self) -> None:
        return None


async def test_request_emits_structured_log_without_secrets(
    make_settings: Callable[..., Settings], stub_token: Any, caplog: Any
) -> None:
    caplog.set_level(logging.INFO, logger="halo_mcp")
    client = HaloClient(make_settings(), http=RecordingHTTP(), token_provider=stub_token)
    await client.get("/Tickets")

    records = [r for r in caplog.records if r.name.startswith("halo_mcp")]
    assert records, "expected at least one halo_mcp log record"
    record = records[-1]
    assert record.status == 200
    assert record.path == "/Tickets"
    assert record.method == "GET"
    # No secret material may appear anywhere in the formatted line.
    text = record.getMessage() + str(record.__dict__)
    assert "Bearer" not in text
    assert "test-access-token" not in text
    assert "test-client-secret" not in text


def test_configure_logging_is_idempotent_and_stderr() -> None:
    from halo_mcp.observability import configure_logging, get_logger

    logger = get_logger()
    saved_handlers = logger.handlers[:]
    saved_propagate = logger.propagate
    saved_level = logger.level
    try:
        configure_logging("DEBUG", "json")
        configure_logging("INFO", "text")  # second call must not stack handlers
        assert len(logger.handlers) == 1
        assert logger.level == logging.INFO
        assert logger.handlers[0].stream is sys.stderr
    finally:
        logger.handlers[:] = saved_handlers
        logger.propagate = saved_propagate
        logger.setLevel(saved_level)
