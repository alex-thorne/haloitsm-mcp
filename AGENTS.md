# AGENTS.md — conventions for working in this repository

This is the **canonical** instructions file. The per-tool instruction files are
symlinks to it (see the README for the exact filenames), so there is a single
source of truth on disk. Keep this file **tool-neutral** — write "the agent",
not the name of any specific assistant, and do not use any tool-specific import
syntax.

## What this project is

A **local-first stdio MCP server** that wraps the **Halo ITSM** REST API. It is
consumed by any MCP client (see `docs/mcp-clients.md` for per-client
registration). The server binary is identical for every client; only the
registration file differs.

- **No network egress except the configured Halo instance.** The only outbound
  calls are to `HALO_API_URL` (the API) and `HALO_AUTH_URL` (the token
  endpoint). Both come from configuration — never hardcode a hostname.
- **No telemetry, analytics, or third-party cloud calls.** CI enforces this with
  an egress-guard step.

## Auth & secrets policy

- Configuration is **environment-only**, via a git-ignored `.env` file (see
  `.env.example` for the contract) loaded by `pydantic-settings`.
- **Never hardcode** a secret, token, or instance host.
- **Never log** the access token or client secret. The client secret is held as
  a `SecretStr`; auth failures raise a typed error with a redacted message.

## Read / write split (enforced server-side)

- **Read tools are always registered** (`tools/read.py`).
- **Write tools are registered only when `HALO_ENABLE_WRITES=true`**
  (`tools/write.py`). Even then, every write tool requires `confirm=True` and
  refuses otherwise. When the host advertises elicitation, the tool additionally
  asks for interactive confirmation; if elicitation is not advertised, the gate
  falls back to the `confirm` flag; if elicitation is advertised but the call
  errors, the write is **refused (fail-closed)** — the tool never proceeds on an
  ambiguous response.
- Because the gate is **server-side**, it protects every client regardless of
  that client's own tool-allowlisting.

## ⚠️ POST-upsert safety

Halo uses `POST` for both create **and** update on Tickets/Actions/Users/Client/
Agent. **Omitting `id` silently creates a duplicate.** Update operations go
through `HaloClient.post_update`, which refuses to fire without an explicit
non-empty `id`. Any new update tool MUST include the record `id`.

## How to add a Halo tool

1. Add a typed `@mcp.tool` function in `tools/read.py` (or `tools/write.py`,
   behind the write gate, with a required `confirm: bool`).
   Simple read resources call `fetch_page(client, …)` (for lists) and the
   `fetch_one(client, …)` helper (for single-record lookups). Heavy endpoints
   (e.g. reports) may pass `timeout=client.long_timeout`.
2. Map the tool parameters to the Halo query/body. Confirm exact endpoint casing
   against your instance's apidoc; keep paths tolerant.
3. Return a **compact projection** (use a DTO in `models.py`) — not the raw Halo
   blob — to keep tool output small.
4. Add a respx-mocked test driving it through the in-memory FastMCP client
   (`tests/test_tools_read.py` / `tests/test_tools_write.py`). Write the failing
   test first.
5. Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src &&
   uv run pytest` until green.

## Conventions

- **Python 3.12**, managed by **uv**. `uv sync --frozen` reproduces from
  `uv.lock`.
- **ruff** (lint + format) and **mypy** must be clean before committing.
- **TDD**: write the failing test first, watch it fail, then implement.
- No real network I/O in tests — respx mocks all calls.
- British spelling in docs.
