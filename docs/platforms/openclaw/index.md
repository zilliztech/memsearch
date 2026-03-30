# OpenClaw Plugin

**Semantic memory for [OpenClaw](https://github.com/openclaw/openclaw) agents.** A TypeScript plugin with `kind: memory` that replaces OpenClaw's built-in memory-core with hybrid semantic search.

---

## Why memsearch over memory-core?

OpenClaw ships with **memory-core**, a built-in memory plugin backed by SQLite + [sqlite-vec](https://github.com/asg017/sqlite-vec). It works out of the box, but has limitations that become apparent at scale:

| Aspect | memory-core (built-in) | memsearch |
|--------|----------------------|-----------|
| **Vector backend** | SQLite + sqlite-vec (single-file, embedded) | [Milvus](https://milvus.io/) -- scales from embedded to distributed cluster |
| **Search** | Dense vector only | Hybrid: dense + BM25 sparse + RRF fusion (better keyword recall) |
| **Storage format** | SQLite database (opaque) | Plain `.md` files (human-readable, git-friendly, editable) |
| **Multi-agent isolation** | Shared database | Per-agent directory + per-agent Milvus collection |
| **Progressive disclosure** | Single-layer (search only) | Three-layer: search → expand → transcript drill-down |
| **Embedding model** | Depends on configuration | Pluggable: ONNX bge-m3 (default), OpenAI, Google, Voyage, Ollama |
| **Data portability** | Locked in SQLite | Copy `.md` files, rebuild index anywhere |
| **Cross-platform** | OpenClaw only | Same memories accessible from Claude Code, Codex, OpenCode |

### When to stay with memory-core

memory-core is the right choice if you want zero-dependency built-in memory with no extra installation. It works well for single-agent setups with moderate history depth.

### When to switch to memsearch

Switch when you need: hybrid search (keyword + semantic), cross-platform memory sharing, human-readable storage, per-agent isolation, or when memory-core's dense-only search misses results that contain specific terms or identifiers.

---

## Per-Agent Isolation

OpenClaw supports multiple agents (e.g., `main`, `work`, custom agents). memsearch provides **automatic per-agent memory isolation** -- no configuration needed:

- **Separate memory directories**: `~/.openclaw/workspace/.memsearch/memory/` for main, `~/.openclaw/workspace-work/.memsearch/memory/` for work agent
- **Separate Milvus collections**: `ms_openclaw_main`, `ms_openclaw_work`
- **Context-driven**: The `agentId` from OpenClaw's tool factory context drives isolation automatically

This means the main agent's debugging notes don't pollute the work agent's project context, and vice versa. Each agent builds its own independent memory timeline.

---

## When Is This Useful?

- **Multi-agent workflows.** You use OpenClaw's main agent for general coding and a work agent for devops. Each needs its own context -- memsearch isolates them automatically.
- **Long-running agent sessions.** OpenClaw agents can run for extended periods in TUI mode. memsearch captures every turn with debounced llm_output hooks, so nothing is lost even in marathon sessions.
- **Cross-platform memory.** You use OpenClaw for some projects and Claude Code for others. memsearch's markdown-based storage means memories are portable -- the same `.md` files work with any plugin.
- **Auditing agent behavior.** memsearch's three-layer drill-down lets you trace from a summary back to the original JSONL transcript, useful for understanding what the agent actually did.

---

## Key Features

- **Automatic capture** -- conversations summarized and saved after each LLM response via debounced `llm_output` hook
- **Three-layer progressive recall** -- search, expand, and drill into original transcripts ([details](memory-tools.md))
- **Multi-agent isolation** -- each agent gets its own memory directory and Milvus collection
- **Cold-start context** -- recent memories injected on agent start via `before_agent_start` hook
- **ONNX embedding by default** -- no API key required, runs locally on CPU
- **Fallback capture** -- `agent_end` hook catches turns missed in non-interactive mode

---

## Pages

- [Installation](installation.md) -- prerequisites, install, uninstall
- [How It Works](how-it-works.md) -- capture architecture, cold-start, memory files, multi-agent isolation
- [Memory Tools](memory-tools.md) -- three registered tools, progressive recall, comparisons
