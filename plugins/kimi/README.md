# Memsearch for Kimi Code CLI

Semantic memory for the Kimi Code CLI agent (Moonshot's coding agent, `~/.kimi-code/bin/kimi`).

- **Kimi-native**: capture + transcript read Kimi's own store (`~/.kimi-code/session_index.jsonl` + `sessions/*/agents/main/wire.jsonl`)
- **Shared**: search reads the same per-project Milvus collection that the Claude Code / OpenCode / Codex / Zed / Hermes captures write — one memory per project, every agent recalls everything

## Install

```bash
uv tool install "memsearch[onnx]"        # the memsearch CLI (shared backend)
cd plugins/kimi
python3 -m venv .venv && .venv/bin/pip install fastmcp
```

Register the server in Kimi's MCP config (`~/.kimi-code/mcp.json`, user-level, or `.kimi-code/mcp.json` in a project):

```json
{
  "mcpServers": {
    "memsearch": {
      "command": "/path/to/plugins/kimi/.venv/bin/python",
      "args": ["/path/to/plugins/kimi/server/memsearch_mcp_server.py"]
    }
  }
}
```

New Kimi sessions expose `mcp__memsearch__memory_*` (run `/mcp` in the TUI to verify). The kimi capture daemon (launchd, 120s poll + 2h re-index) keeps the daily `.md` files + index fresh without the agent asking.

## Tools

| Tool | Purpose |
| --- | --- |
| `memory_search` | semantic search over the current project's shared memories |
| `memory_get` | expand a chunk to its full markdown section |
| `memory_transcript` | read the original turns of a Kimi session (wire.jsonl) |
| `memory_capture` | capture recent Kimi sessions into the shared daily files + re-index |
