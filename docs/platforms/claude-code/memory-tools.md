# Memory Surface

The Claude Code plugin does not register MCP tools. Instead, it exposes memory through a combination of:

- **Hooks** for session lifecycle and cold-start awareness
- The **`memory-recall` skill** for autonomous retrieval
- The **`memsearch` CLI** for manual diagnostics and debugging

This page documents that practical memory surface in one place.

---

## Main Retrieval Entry Point

For normal use, the entry point is the `memory-recall` skill.

**Manual invocation:**

```text
/memory-recall what did we discuss about the auth refactor?
```

**Automatic invocation:** ask a question naturally when history matters:

```text
We changed the caching approach last week — what did we decide?
```

Claude can invoke the skill automatically when the question benefits from historical context.

---

## Retrieval Layers

The `memory-recall` skill uses the same three-layer progressive disclosure model described in [Memory Recall](memory-recall.md):

| Layer | Backend command | What it does |
|------|------------------|--------------|
| L1 | `memsearch search` | Find relevant indexed snippets |
| L2 | `memsearch expand` | Expand a chunk into its full markdown section |
| L3 | `memsearch transcript` / `transcript.py` | Drill into the original Claude Code conversation |

The important difference from MCP-style systems is that these steps run inside the skill's forked subagent context, not as permanently registered tools in the main conversation.

---

## Manual CLI Surface

The plugin is built on the `memsearch` CLI, so you can inspect and debug memory behavior manually from the shell.

| Command | Typical use |
|---------|-------------|
| `memsearch search "<query>" --top-k 5 --json-output` | Check whether relevant memories are being found |
| `memsearch expand <chunk_hash>` | Read the full markdown section around a result |
| `memsearch transcript <jsonl>` | Inspect the original transcript |
| `memsearch stats` | Check collection name, chunk count, and dimensions |
| `memsearch index .memsearch/memory/ --force` | Rebuild the index |
| `memsearch reset --yes` | Drop indexed data for the current collection |

When debugging Claude Code plugin issues, `search`, `expand`, and `stats` are the fastest sanity checks.

---

## Observability Surface

Beyond the recall skill itself, the plugin exposes several lightweight signals:

- **SessionStart status line** — shows embedding provider, Milvus path, and collection
- **`[memsearch] Memory available` hint** — reminds Claude that recall exists
- **`.memsearch/memory/YYYY-MM-DD.md`** — the markdown source of truth
- **`.memsearch/.watch.pid`** — indicates whether the watch process is running
- **Claude debug logs** (`claude --debug`) — reveal hook JSON, including `systemMessage` and `additionalContext`

These are documented in more detail in [Troubleshooting](troubleshooting.md).

---

## When to Use Which Surface

| Goal | Best entry point |
|------|------------------|
| Ask Claude about past work | Natural language prompt or `/memory-recall` |
| Verify memories exist at all | `memsearch stats` |
| Check whether search can find a topic | `memsearch search` |
| Inspect full context around a hit | `memsearch expand` |
| Inspect the exact original exchange | `memsearch transcript` |
| Rebuild stale/broken index state | `memsearch index --force` |

---

## Related Pages

- [Installation](installation.md)
- [How It Works](how-it-works.md)
- [Memory Recall](memory-recall.md)
- [Troubleshooting](troubleshooting.md)
