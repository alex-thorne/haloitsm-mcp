# halo-mcp

A **local-first MCP server** that wraps the
[Halo ITSM](https://haloitsm.com/) REST API. It exposes a small set of typed
tools (tickets, assets, clients, users, agents, lookups) to any MCP client —
Claude Code, GitHub Copilot, Cursor — over **stdio**.

- **Read-only by default.** Write tools are gated behind `HALO_ENABLE_WRITES`
  and a per-call `confirm`.
- **No egress except your Halo instance. No telemetry.** Enforced in CI.
- **Secrets stay in `.env`** (git-ignored). Nothing is hardcoded.

## Requirements

- [uv](https://docs.astral.sh/uv/) (manages Python and dependencies)
- Python 3.12 (uv will provision it from `.python-version`)

## Setup

```bash
uv sync                       # create the venv and install from uv.lock
cp .env.example .env          # then fill in the values (see the runbook below)
uv run halo-mcp-smoke         # prove end-to-end connectivity (read-only)
```

`uv run halo-mcp` starts the server over stdio. See
[`docs/mcp-clients.md`](docs/mcp-clients.md) to register it with your client.

## Halo API application runbook (admin, on your instance)

You need a **service application** using the OAuth2 **client-credentials**
grant (machine-to-machine).

1. Halo admin → **Configuration → Integrations → HaloITSM API** (the "API"
   page).
2. At the top of that page, copy the three values: **Resource Server**,
   **Authorisation Server**, and **Tenant**.
3. **View Applications → New**. Set **Authentication Method = "Client ID and
   Secret (Services)"**.
4. Copy the **Client ID**; generate and copy the **Client Secret**.
5. Assign **least-privilege permissions** to the application — read tickets,
   assets, customers, users, agents. **Only** add edit permissions when you
   intend to enable writes.
6. Derive the env values:
   - `HALO_API_URL` = `<Resource Server>/api`
   - `HALO_AUTH_URL` = the token endpoint. **The form varies by instance** —
     two conventions exist:
     - `https://<Authorisation Server>/token` — set `HALO_TENANT` so `?tenant=`
       is appended, **or**
     - `https://<Resource Server>/auth/token`.

     The API page's *Authorisation Server* value is authoritative; confirm by
     running the smoke test and using whichever form returns a token.
   - `HALO_TENANT` = the Tenant value (only needed for the `?tenant=` form).
   - `HALO_CLIENT_ID` / `HALO_CLIENT_SECRET` from step 4.

## Environment contract

| Var | Required | Purpose |
| --- | --- | --- |
| `HALO_API_URL` | yes | Resource Server API base, e.g. `https://<instance>.haloitsm.com/api` |
| `HALO_AUTH_URL` | yes | Full token endpoint (see runbook — form varies by instance) |
| `HALO_TENANT` | no | Tenant name, appended as `?tenant=` when the auth server requires it |
| `HALO_CLIENT_ID` | yes | From the registered API application |
| `HALO_CLIENT_SECRET` | yes | From the registered API application |
| `HALO_SCOPES` | no | Space-separated OAuth scopes; defaults to a least-privilege read set |
| `HALO_ENABLE_WRITES` | no | `false` (default). Must be exactly `true` to register write tools |
| `HALO_PAGE_SIZE` | no | Default `50`, max `100` (Halo caps list responses at 100/page) |
| `HALO_TIMEOUT` | no | httpx timeout in seconds, default `30` |
| `HALO_LOG_LEVEL` | no | Log level for the `halo_mcp` logger: `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |
| `HALO_LOG_FORMAT` | no | `text` (default) or `json`; logs go to **stderr only** |
| `HALO_LONG_TIMEOUT` | no | httpx timeout for heavy endpoints (e.g. reports), default `120` |

Default read scopes:
`read:tickets read:assets read:customers` — a least-privilege read set. There is
no `read:users`/`read:agents` scope (requesting either yields `invalid_scope`);
that directory data needs no dedicated scope.

Some optional tools (`list_suppliers`, `list_opportunities`, `list_invoices`,
`list_appointments`) touch resources outside that default set. If your grant
omits the required scope they return an `insufficient_scope` envelope — naming
the path and your granted scopes — rather than a raw error. Widen `HALO_SCOPES`
**and** the Halo application's permissions to enable them.

When enabling writes, the operator must widen scopes (e.g. add `edit:tickets`)
**and** grant the matching permissions on the Halo application. The server does
not auto-add edit scopes.

## Tools

**Read (always available):** `list_tickets`, `get_ticket`, `search_tickets`,
`list_ticket_actions`, `list_assets`, `get_asset`, `list_clients`, `list_users`,
`list_agents`, `get_agent`, `list_teams`, `list_statuses`,
`list_priorities`, `list_slas`, `list_categories`, `whoami`,
`list_sites`, `get_site`, `list_suppliers`, `get_supplier`, `list_ticket_types`,
`list_projects`, `get_project`, `list_opportunities`, `get_opportunity`,
`list_invoices`, `get_invoice`, `list_items`, `get_item`,
`list_appointments`, `get_appointment`, `list_attachments`, `list_reports`.

**Write (only when `HALO_ENABLE_WRITES=true`):** `create_ticket`,
`update_ticket`, `add_action`, `set_ticket_status`,
`update_client`, `update_user`, `create_site`, `update_site`,
`create_asset`, `update_asset`.
Each takes a required `confirm` and refuses unless it is `true`; on hosts that
support elicitation it also asks for interactive confirmation.

### Observability

Structured log lines go to **stderr only** (never stdout, which carries the MCP
protocol). Set `HALO_LOG_LEVEL` (`DEBUG`/`INFO`/`WARNING`/`ERROR`) and
`HALO_LOG_FORMAT` (`text` or `json`). Each log line records method, path,
HTTP status, duration, attempt count, and a request id. The access token,
client secret, `Authorization` header, and request/response bodies are **never**
logged.

> ⚠ **POST-upsert warning.** Halo uses `POST` for both create and update.
> Omitting `id` silently creates a **duplicate**, so update tools always send the
> record `id` and the client refuses an update without one.

## Smoke test

```bash
uv run halo-mcp-smoke
```

Authenticates via client-credentials, runs `whoami`, fetches the first page of
tickets, and prints `record_count` + the first few ids/summaries. **Read-only**,
exits non-zero on failure. This is the single command that proves end-to-end
connectivity to your instance.

## Transport

The default transport is **stdio** (`uv run halo-mcp`). To run over HTTP
instead, change the entry point to:

```python
mcp.run(transport="http", host="127.0.0.1", port=8000)
```

> ⚠ HTTP exposes an **inbound** surface. Put it behind authentication before
> sharing it with a team or exposing it beyond localhost.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

Conventions and the "how to add a tool" recipe live in
[`AGENTS.md`](AGENTS.md) (the canonical instructions file; `CLAUDE.md` and
`.github/copilot-instructions.md` are symlinks to it).
