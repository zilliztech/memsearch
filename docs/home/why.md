# Why memsearch?

## One Memory, Every Agent

memsearch provides persistent memory plugins for **4 major AI coding agent platforms**: [Claude Code](../platforms/claude-code.md), [OpenClaw](../platforms/openclaw.md), [OpenCode](../platforms/opencode.md), and [Codex CLI](../platforms/codex.md).

Memories written in one platform are searchable from any other. A conversation in Claude Code becomes available context in OpenClaw, Codex, and OpenCode — no extra setup, no manual export.

## Both for Agent Users and Agent Developers

- **Agent Users**: install a plugin, get persistent memory. Zero commands to learn, zero manual saving.
- **Agent Developers**: a complete [CLI](../cli.md) and [Python API](../python-api.md) for building memory and harness engineering into your own agents.

One tool, two audiences.

## Markdown is the Source of Truth

Inspired by [OpenClaw](https://github.com/openclaw/openclaw) — your memories are plain `.md` files: human-readable, editable, version-controllable.

Milvus is a **shadow index** — a derived, rebuildable cache. Delete the index, run `memsearch index`, and everything is back. The real data never leaves your markdown files.

## Architecture

See the [Architecture](../architecture.md) deep dive and [Design Philosophy](../design-philosophy.md) for the full picture.

## Features

- **Hybrid Search** — BM25 sparse + dense vector + RRF reranking for the best recall
- **Smart Dedup** — SHA-256 content hashing skips unchanged content on re-index
- **Live Sync** — file watcher auto-indexes changes in real time
- **Progressive Disclosure** — 3-layer recall: search → expand → transcript
- **Pluggable Embeddings** — ONNX (local, free), OpenAI, Google, Voyage, Ollama
