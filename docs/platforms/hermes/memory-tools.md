# Memory Tools

The plugin registers an MCP server (fastmcp) that Hermes connects to via its
built-in MCP client (`hermes mcp add memsearch --command ...`). The tools are
first-class Hermes tools, available to the agent during any conversation.

## Tool Reference

| Tool | What it does |
|------|--------------|
| **memory_search** | Semantic search over the shared memory (hybrid BM25 + dense + RRF) via `memsearch search --json-output` |
| **memory_get** | Expand a chunk to its full markdown section via `memsearch expand` |
| **memory_transcript** | Read the original turns of a Hermes session from `~/.hermes/state.db` |
| **memory_capture** | Capture recent Hermes sessions into the daily memory file + re-index (self-contained, idempotent) |

## How to Trigger

Ask naturally: *"recall what we decided about X"*, *"have I seen this before"*, or *"what did past sessions say about Y"*. The agent calls `memory_search` → `memory_get` → `memory_transcript` as needed — the same three-layer progressive recall as the OpenCode / OpenClaw plugins.

## Three-Layer Progressive Recall

1. **Search** — `memory_search` for the core intent; try 1-2 alternate phrasings if weak.
2. **Expand** — `memory_get` on the best hit for the full section + context.
3. **Transcript** — when the chunk carries a `hermes session_id:<sid>` anchor, `memory_transcript` reads the exact turns from state.db.

## Cross-Agent Recall

All platforms write the same `.md` format + collection — `memory_search` returns Claude Code, OpenCode, Zed, and Hermes memories mixed by relevance.

## Tips

- Collection: derived from the memory home (`ms_hermes_*` by default).
- If search feels stale, call `memory_capture` (or the daemon re-indexes every 2h).