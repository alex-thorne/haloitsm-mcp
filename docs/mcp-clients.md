# Registering the Halo MCP server with each client

The server binary is **identical** for every harness — `uv run halo-mcp` over
stdio. Only the registration file differs (additive, not a fork). Secrets always
live in `.env` (loaded by the process); never put `HALO_CLIENT_SECRET` in any of
these JSON files.

The read/write split is enforced **server-side** (`HALO_ENABLE_WRITES` +
`confirm=True`), so it protects you regardless of which client connects or how
that client allowlists tools.

## Claude Code — `.mcp.json` (committed)

Root key is **`mcpServers`**.

```json
{
  "mcpServers": {
    "halo-itsm": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "halo-mcp"],
      "env": { "HALO_ENABLE_WRITES": "${HALO_ENABLE_WRITES:-false}" }
    }
  }
}
```

Verify with `claude mcp list` or the `/mcp` command — `halo-itsm` should appear.

## GitHub Copilot in VS Code — `.vscode/mcp.json` (committed)

⚠ Root key is **`servers`**, *not* `mcpServers` — this is the most common
cross-tool mistake. Copilot's MCP tools only appear in **Agent mode**. On
macOS/Linux you can sandbox the stdio server (which auto-approves its tool
calls); set the allowed domain(s) to your Halo host(s).

```jsonc
{
  "servers": {
    "halo-itsm": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "halo-mcp"],
      "sandboxEnabled": true
    }
  },
  "sandbox": { "network": { "allowedDomains": ["<your-instance>.haloitsm.com"] } }
}
```

## GitHub Copilot CLI — no committed file

Register once into `~/.copilot/mcp-config.json`:

```
copilot mcp add halo-itsm -- uv run halo-mcp
```

## Cursor — `.cursor/mcp.json` (or global `~/.cursor/mcp.json`)

Cursor uses the **`mcpServers`** root key (same shape as Claude Code):

```json
{
  "mcpServers": {
    "halo-itsm": {
      "command": "uv",
      "args": ["run", "halo-mcp"],
      "env": { "HALO_ENABLE_WRITES": "false" }
    }
  }
}
```

## GitHub.com Copilot cloud agent / code review

Configure in the repo's **Settings → Copilot → MCP servers** with a JSON object
using `mcpServers`, `type: "local"`, and env vars provided as
`COPILOT_MCP_`-prefixed Actions/Agents secrets.

> ⚠ **Topology caveat.** The cloud agent runs in GitHub's ephemeral Actions
> runner. It will **not** have a network route to a self-hosted / VPN-only Halo
> instance, and stdio there means installing `uv` + this package into the runner.
> For a private Halo, treat the cloud agent as **out of scope** — the local
> harnesses (Claude Code, Copilot-in-IDE, Copilot CLI, Cursor) all run on your
> machine and reach Halo fine. If you ever genuinely need the cloud agent, that
> is the trigger to switch the server to the streamable-HTTP transport behind
> auth (see the README transport note) and expose it deliberately.
