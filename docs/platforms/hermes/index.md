# Hermes Plugin

Semantic memory for [Hermes Agent](https://hermes-agent.nousresearch.com) (Nous Research). Hermes runs in your terminal and stores every session in a local SQLite DB (`~/.hermes/state.db`), which makes its capture model the same as the **OpenCode** plugin (poll the DB, write the shared format). Recall is an **MCP server** exposing memory tools — the same model as the Zed extension.

## Installation

Follow [Installation](./installation.md). The short version:

```bash
plugins/hermes/install.sh <project_dir>
hermes mcp add memsearch --command "<venv>/bin/python <plugin>/server/memsearch_mcp_server.py"
```

## Key Features

- **Cross-platform memory** — capture into the same `memory/YYYY-MM-DD.md` + Milvus collection the other plugins write.
- **MCP recall** — the agent gets `memory_search`, `memory_get`, `memory_transcript`, `memory_capture` as first-class tools via Hermes's built-in MCP client.
- **Capture via state.db poller** — a launchd daemon (2m poll) or cron reads `~/.hermes/state.db`, appends new user/assistant turns, re-indexes.
- **Dedicated memory home** — Hermes conversations live in `~/hermes/.memsearch/` (override `HERMES_MEMORY_HOME`) so they don't pollute project repos.

## When Is This Useful?

Hermes is commonly paired with Claude Code / OpenCode / Zed in the same repos. With this plugin, a decision made in a Hermes session is searchable from Zed the next day, and vice versa.

## Platform Notes

| Aspect | Hermes |
|--------|--------|
| Plugin type | MCP server (Python, fastmcp) |
| Capture method | SQLite poller (launchd daemon / cron) on `~/.hermes/state.db` |
| Recall mechanism | memory_search tool (MCP) |
| L3 transcript | Hermes `state.db` |
| Isolation | Dedicated collection (`ms_hermes_*`) |