# OpenCode Plugin

**Semantic memory for [OpenCode](https://github.com/nicepkg/opencode).** A TypeScript plugin that captures conversations via a background SQLite daemon and provides three-layer memory recall.

---

## Why memsearch for OpenCode?

OpenCode does not ship with a built-in memory system. Several third-party options exist, but memsearch offers a unique combination of features:

| Aspect | memsearch | opencode-mem | true-mem |
|--------|-----------|-------------|----------|
| **Vector backend** | [Milvus](https://milvus.io/) -- hybrid search (dense + BM25 + RRF) | SQLite + [USearch](https://github.com/unum-cloud/usearch) (dense only) | Varies by implementation |
| **Search quality** | Hybrid: semantic similarity + keyword matching fused with RRF | Dense vector similarity only | Typically dense only |
| **Storage format** | Plain `.md` files (human-readable, git-friendly) | SQLite database (opaque) | Varies |
| **Cross-platform** | Same memories accessible from Claude Code, OpenClaw, Codex | OpenCode only | Single platform |
| **Capture method** | Background daemon polls SQLite | Hook-based | Varies |
| **Progressive disclosure** | Three-layer: search → expand → transcript | Typically single-layer | Typically single-layer |
| **Embedding model** | Pluggable: ONNX bge-m3 (default), OpenAI, Google, Voyage, Ollama | Typically fixed | Varies |

### The Cross-Platform Advantage

If you use multiple AI coding agents (e.g., OpenCode for some projects, Claude Code for others), memsearch gives you a **unified memory layer**. Memories captured in OpenCode are searchable from Claude Code, and vice versa -- all plugins write the same markdown format and use the same Milvus backend.

---

## Key Features

- **SQLite-based capture** -- background daemon polls OpenCode's database for new turns, no hook limitations
- **Three-layer progressive recall** -- search, expand, and drill into original conversations ([details](memory-tools.md))
- **Automatic summarization** -- each turn summarized via `opencode run` with isolated config
- **Cold-start context** -- recent memories injected via `system.transform` hook
- **ONNX embedding by default** -- no API key required, runs locally on CPU
- **Daemon self-management** -- PID file singleton, automatic restart, persistent state across daemon restarts

---

## When Is This Useful?

- **Multi-day projects.** OpenCode sessions are ephemeral by default. memsearch captures every conversation so you can pick up where you left off without re-explaining context.
- **Cross-platform workflows.** You switch between OpenCode, Claude Code, or Codex depending on the task. memsearch provides continuous memory across all of them.
- **Team environments.** Commit `.memsearch/memory/` to git and team members can search the project's decision history.
- **Debugging trails.** When a bug resurfaces, memsearch can recall what was tried before -- which approaches failed, what worked, and why.

---

## Pages

- [Installation](installation.md) -- prerequisites, automated and manual install
- [How It Works](how-it-works.md) -- capture daemon, cold-start, memory files, architecture
- [Memory Tools](memory-tools.md) -- three registered tools, progressive recall, comparisons
