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

**Architecture: 4 shell hooks + 1 skill + 1 background watcher**

```
ccplugin/
├── hooks/
│   ├── common.sh                # Shared setup: PATH, memsearch detection, collection name, watch PID
│   ├── session-start.sh         # SessionStart: start watch, write session heading, inject recent memories
│   ├── user-prompt-submit.sh    # UserPromptSubmit: lightweight hint reminding Claude about memory skill
│   ├── stop.sh                  # Stop: parse transcript → haiku summarize → append to daily .md (async)
│   ├── session-end.sh           # SessionEnd: stop watch process
│   └── parse-transcript.sh      # Deterministic JSONL-to-text parser (used by stop.sh)
├── scripts/
│   └── derive-collection.sh     # Derive per-project collection name from project path
└── skills/
    └── memory-recall/
        └── SKILL.md             # Skill (context: fork): search → expand → transcript in subagent
```

**Key design: skill-based memory recall.** Memory retrieval is handled by a `memory-recall` skill that runs in a forked subagent context (`context: fork`). Claude automatically invokes the skill when it judges the user's question could benefit from historical context. The subagent autonomously performs search, evaluates relevance, expands promising results, and returns a curated summary — all without polluting the main conversation context.

**Three-layer progressive disclosure (all in subagent):**
1. **L1 (search):** Subagent runs `memsearch search` to find relevant chunks
2. **L2 (expand):** Subagent runs `memsearch expand <chunk_hash>` to get full markdown sections
3. **L3 (transcript):** Subagent runs `memsearch transcript <jsonl>` to drill into original conversations

**Supporting hooks:**
- `SessionStart` injects cold-start context (recent daily logs) so Claude knows history exists
- `UserPromptSubmit` returns a lightweight `systemMessage` hint ("[memsearch] Memory available") to increase skill trigger awareness
- `Stop` hook is async and non-blocking — calls `claude -p --model haiku` to summarize, appends to daily `.md`

When modifying hooks/skills, keep in mind:
- All hooks output JSON to stdout (`additionalContext` for context injection, `systemMessage` for visible hints, or empty `{}`)
- `common.sh` is sourced by every hook — changes there affect all hooks. It derives a per-project `COLLECTION_NAME` via `derive-collection.sh` and passes `--collection` automatically through `run_memsearch()` and `start_watch()`
- The watch process uses a PID file (`.memsearch/.watch.pid`) for singleton behavior
- `stop.sh` has a recursion guard (`stop_hook_active`) since it calls `claude -p` internally
- The `memory-recall` skill uses `context: fork` — the subagent has its own context window and does not see main conversation history

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
