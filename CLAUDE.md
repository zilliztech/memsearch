# CLAUDE.md

<!-- This file is for AI agents (Claude Code, Cursor, Copilot, etc.) working in this repository.
     It also serves as a shared project memory — recording conventions, architecture decisions,
     and common patterns that all contributors (human or AI) should follow.
     Symlinked as AGENT.md and MEMORY.md for compatibility with other tools. -->

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install in development mode
uv sync --all-extras

# Run all tests (use python -m pytest to avoid system pytest conflicts)
uv run python -m pytest

# Run a single test file
uv run python -m pytest tests/test_chunker.py

# Run a specific test
uv run python -m pytest tests/test_store.py::test_upsert_and_search -v

# Serve docs locally
uv run mkdocs serve

# Run the CLI
uv run memsearch --help
```

## Architecture

**memsearch** is a semantic memory search engine for markdown knowledge bases, built on Milvus.

### Data Flow

```
Markdown files → Scanner → Chunker → Embedder → MilvusStore
                                                      ↓
                               User query → Embedder → Hybrid Search (dense + BM25 + RRF) → Results
```

### Core Library (`src/memsearch/`)

- **`core.py`** — `MemSearch` class: the public Python API that orchestrates everything. Entry point for `index()`, `search()`, `compact()`, `watch()`.
- **`store.py`** — `MilvusStore`: Milvus wrapper handling collection creation, upsert, hybrid search (dense cosine + BM25 sparse + RRF reranking), and cleanup. The `chunk_hash` (composite ID of source+lines+content+model) is the VARCHAR primary key.
- **`chunker.py`** — Splits markdown by headings into `Chunk` dataclasses. SHA-256 content hash enables dedup. `compute_chunk_id()` generates composite IDs matching OpenClaw's format.
- **`embeddings/__init__.py`** — `EmbeddingProvider` protocol + lazy-loading factory (`get_provider()`). Providers: openai, google, voyage, ollama, local.
- **`scanner.py`** — Walks directories to find `.md`/`.markdown` files, returns `ScannedFile` list.
- **`config.py`** — Layered TOML config: dataclass defaults → `~/.memsearch/config.toml` → `.memsearch.toml` → CLI flags.
- **`cli.py`** — Click CLI wrapping the Python API. All commands resolve config via `resolve_config()` then instantiate `MemSearch`.
- **`watcher.py`** — `watchdog`-based file watcher with debounce, used by `memsearch watch` and the Claude Code plugin.
- **`compact.py`** — LLM-powered chunk summarization (OpenAI/Anthropic/Gemini).
- **`transcript.py`** — JSONL transcript parser for Claude Code conversation files.

### Claude Code Plugin (`ccplugin/`)

The plugin is a first-class component of memsearch — it's the primary real-world application that demonstrates the library in action. It gives Claude Code automatic persistent memory across sessions with zero user intervention.

**Architecture: 4 shell hooks + 1 background watcher**

```
ccplugin/hooks/
├── common.sh                # Shared setup: PATH, memsearch detection, watch PID management
├── session-start.sh         # SessionStart: start watch, write session heading, inject recent memories
├── user-prompt-submit.sh    # UserPromptSubmit: semantic search → inject top-k via additionalContext
├── stop.sh                  # Stop: parse transcript → haiku summarize → append to daily .md (async)
├── session-end.sh           # SessionEnd: stop watch process
└── parse-transcript.sh      # Deterministic JSONL-to-text parser (used by stop.sh)
```

**Key design: push-based memory.** The `UserPromptSubmit` hook runs `memsearch search` on every user prompt and injects relevant memories as `additionalContext` — Claude never needs to decide whether to search. This is fundamentally different from MCP-based approaches where the agent must proactively pull memories.

**Three-layer progressive disclosure:**
1. **L1 (automatic):** Hook injects top-k search results with 200-char previews and `chunk_hash` IDs
2. **L2 (on-demand):** Claude runs `memsearch expand <chunk_hash>` to see the full markdown section
3. **L3 (on-demand):** Claude runs `memsearch transcript <jsonl>` to drill into the original conversation

**Stop hook is async and non-blocking.** It fires after Claude finishes each response, calls `claude -p --model haiku` to summarize, and appends to `.memsearch/memory/YYYY-MM-DD.md` with session anchors. The user can continue chatting immediately.

When modifying hooks, keep in mind:
- All hooks output JSON to stdout (`additionalContext` for context injection, or empty `{}`)
- `common.sh` is sourced by every hook — changes there affect all hooks
- The watch process uses a PID file (`.memsearch/.watch.pid`) for singleton behavior
- `stop.sh` has a recursion guard (`stop_hook_active`) since it calls `claude -p` internally

## Key Design Decisions

- **Markdown is the source of truth.** Milvus is a derived index, rebuildable anytime from `.md` files.
- **Composite chunk ID as PK.** `hash(source:startLine:endLine:contentHash:model)` — enables natural dedup without a separate cache.
- **Hybrid search by default.** Every collection has both dense vector and BM25 sparse fields. Search uses RRF to combine them.
- **Remote Milvus `query()` requires a filter.** Use `chunk_hash != ""` as a "match all" filter when no filter is provided (Milvus Lite doesn't enforce this, but Milvus Server does).

## Project Conventions

- Uses `uv` + `pyproject.toml` for dependency management (not pip).
- Optional deps via extras: `[google]`, `[voyage]`, `[ollama]`, `[local]`, `[all]`.
- Docs at `docs/` use mkdocs-material. The `site/` directory is build output — do not commit.
- Code and comments in English. Respond to the user in Chinese unless they specify otherwise.
- Always use `uv run python -m pytest` instead of `uv run pytest` to avoid system Python pytest conflicts.
