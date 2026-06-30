"""Structured, secret-free request logging.

Logs are written to STDERR only: under stdio transport STDOUT is the MCP wire
protocol, so a stray stdout line would corrupt the session. We never log the
access token, client secret, Authorization header, or request/response bodies —
only coarse request metadata (method, path, status, duration, attempt) plus a
correlation id.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar

_LOGGER_NAME = "halo_mcp"
_request_id: ContextVar[str] = ContextVar("halo_request_id", default="-")

_STRUCTURED_FIELDS = ("method", "path", "status", "duration_ms", "attempt", "request_id")


def new_request_id() -> str:
    """Generate and bind a short correlation id for the current async context."""
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def current_request_id() -> str:
    return _request_id.get()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", current_request_id()),
        }
        for key in _STRUCTURED_FIELDS:
            if key != "request_id" and hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Install a single stderr handler on the ``halo_mcp`` logger (idempotent)."""
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger(_LOGGER_NAME)
    logger.handlers[:] = [handler]
    logger.setLevel(level.upper())
    logger.propagate = False


def get_logger() -> logging.Logger:
    """Return the ``halo_mcp`` package logger."""
    return logging.getLogger(_LOGGER_NAME)
