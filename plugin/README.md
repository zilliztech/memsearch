# memsearch — Claude Code Plugin

**Automatic persistent memory for Claude Code.** No commands to learn, no manual saving — just install the plugin and Claude remembers what you worked on across sessions.

```bash
claude --plugin-dir /path/to/memsearch/plugin
```

## How It Works

The plugin hooks into 6 Claude Code lifecycle events. Every user prompt triggers a semantic search; every session end writes an AI-generated summary. Memory files are transparent markdown you can read, edit, and version-control.

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    memsearch plugin lifecycle                           │
  └─────────────────────────────────────────────────────────────────────────┘

  SESSION START
  ─────────────
  ┌──────────────┐     ┌─────────────────┐     ┌──────────────────────────┐
  │ SessionStart │────▶│ Read recent     │────▶│ Inject into context      │
  │   hook       │     │ daily .md logs  │     │ { "additionalContext" }  │
  └──────────────┘     │ + memsearch     │     └──────────────────────────┘
                       │   search        │
                       └─────────────────┘

  EVERY USER PROMPT
  ─────────────────
  ┌──────────────────┐     ┌─────────────────┐     ┌────────────────────┐
  │ UserPromptSubmit │────▶│ memsearch search │────▶│ Inject top-3       │
  │   hook           │     │ "$user_prompt"   │     │ relevant memories  │
  └──────────────────┘     │ --top-k 3        │     └────────────────────┘
                           └─────────────────┘
                           (skip if < 10 chars)

  DURING CONVERSATION
  ────────────────────
  ┌──────────────┐     ┌──────────────────┐     ┌──────────────────────┐
  │ PostToolUse  │────▶│ Is .md file in   │─Y──▶│ memsearch index      │
  │ (Write|Edit) │     │ .memsearch/mem/? │     │ .memsearch/memory/   │
  │  async       │     └──────────────────┘     └──────────────────────┘
  └──────────────┘              │N
                                └──▶ skip (no-op)

  SESSION END
  ───────────
  ┌──────────┐     ┌──────────────────────┐     ┌──────────────────────┐
  │  Stop    │────▶│ Agent subagent reads │────▶│ Write AI summary to  │
  │ (agent   │     │ transcript JSONL via │     │ .memsearch/memory/   │
  │  hook)   │     │ $ARGUMENTS           │     │ YYYY-MM-DD.md        │
  └──────────┘     └──────────────────────┘     └──────────┬───────────┘
                                                           │
  ┌──────────────┐                                         │
  │ PreCompact   │──── memsearch index ◀───────────────────┘
  └──────────────┘     (ensure fresh before compaction)

  ┌──────────────┐
  │ SessionEnd   │──── memsearch index (final sync)
  └──────────────┘
```

### Hook Summary

| Hook | Type | Async | Timeout | What it does |
|------|------|-------|---------|-------------|
| **SessionStart** | command | no | 10s | Read recent daily logs + semantic search → inject context |
| **UserPromptSubmit** | command | no | 15s | Semantic search on user prompt → inject relevant memories |
| **PostToolUse** | command | yes | 30s | Index `.md` edits inside `.memsearch/memory/` |
| **Stop** | agent | no | 60s | Read transcript → AI summary → write daily log → index |
| **PreCompact** | command | no | 15s | `memsearch index` before context compaction |
| **SessionEnd** | command | no | 30s | Final `memsearch index` sync |

### Why Stop uses an agent hook

The **Stop** hook is the only one that uses an agent hook (subagent with AI capabilities). All other hooks are simple command (bash) hooks. Here's why:

- **PostToolUse** fires on every Write/Edit — spawning a subagent each time would be too expensive
- **PreCompact / SessionEnd** only need `memsearch index`, no AI reasoning required
- **Stop** fires once per session and needs AI to read the full transcript and generate a meaningful summary — a bash script can't do that

The agent hook subagent receives the transcript path via `$ARGUMENTS`, reads the JSONL file, and writes a structured summary. Zero extra LLM API calls — it uses Claude's built-in subagent capability.

## Memory Storage

All memories live in **`.memsearch/memory/`** inside your project directory:

```
your-project/
└── .memsearch/
    └── memory/
        ├── 2026-02-07.md
        ├── 2026-02-08.md
        └── 2026-02-09.md    ← today's session summaries
```

Each file contains session summaries in plain markdown:

```markdown
## Session 14:30
- Implemented caching system with Redis L1 and in-process LRU L2
- Fixed N+1 query issue in order-service using selectinload
- Decided to use Prometheus counters for cache hit/miss metrics

## Session 17:45
- Debugged React hydration mismatch — Date.now() during SSR
- Added comprehensive test suite for the caching middleware
```

**Markdown is the source of truth.** The Milvus vector index is a derived cache that can be rebuilt at any time with `memsearch index .memsearch/memory/`.

## memsearch plugin vs claude-mem

| | memsearch plugin | claude-mem |
|---|---|---|
| **Prompt-level recall** | Semantic search on **every prompt** | Only at SessionStart |
| **Pre-compaction safety** | **PreCompact hook** ensures fresh index | No PreCompact hook |
| **Session summary** | **Agent hook subagent** — zero extra API calls, no background service | Separate Worker service (port 37777) + Anthropic Agent SDK API calls |
| **Storage format** | **Transparent `.md` files** — human-readable, git-friendly | Opaque SQLite + Chroma binary |
| **Architecture** | 6 bash scripts + 1 agent prompt, ~200 lines total | Node.js/Bun Worker service + Express server + React UI |
| **Runtime dependency** | Python (`memsearch` CLI) | Node.js + Bun runtime |
| **Vector backend** | **Milvus** (Lite → Server → Zilliz Cloud) | Chroma (local only) |
| **Background processes** | **None** — all hooks are stateless | Worker service must be running |
| **Temp files** | **None** — reads transcript via `$ARGUMENTS` | `session.log` intermediate state |
| **Data portability** | Copy `.memsearch/memory/*.md` — that's it | Export from SQLite + Chroma |
| **Cost** | **Zero** extra LLM calls (agent hook is free) | Claude API calls for observation compression |

### Key design differences

**memsearch** takes a **minimalist, Unix-philosophy approach**: each hook is a small, stateless bash script. No background services, no temp files, no opaque databases. The only "smart" part is the Stop agent hook, which leverages Claude's built-in subagent to generate session summaries at zero cost.

**claude-mem** takes a **full-stack approach**: a Worker service compresses every tool observation into structured data via Claude API calls, stores them in SQLite + Chroma with FTS5 full-text indexes, and provides a React web UI for browsing memories. More powerful for heavy use, but significantly more complex.

## Prerequisites

- **memsearch** CLI in PATH — install via:
  ```bash
  pip install memsearch
  # or
  uv tool install memsearch
  ```
- **jq** — for JSON parsing in hook scripts (pre-installed on most systems)
- A configured memsearch backend (`.memsearch.toml` or `~/.memsearch/config.toml`)

## Quick Start

```bash
# 1. Install memsearch
pip install memsearch

# 2. Initialize config (if first time)
memsearch config init

# 3. Launch Claude with the plugin
claude --plugin-dir /path/to/memsearch/plugin

# 4. Have a conversation, then exit. Check your memories:
cat .memsearch/memory/$(date +%Y-%m-%d).md

# 5. Start a new session — Claude remembers!
claude --plugin-dir /path/to/memsearch/plugin
```

## Troubleshooting

**Memories not being injected?**
- Check that `.memsearch/memory/` exists and has `.md` files
- Verify `memsearch search "test query"` works from the command line
- Ensure `jq` is installed: `jq --version`

**Stop hook not writing summaries?**
- The agent hook subagent needs Read/Write tool access — this is a Claude Code limitation for agent hooks
- If it doesn't work, session summaries won't be auto-generated, but all other hooks (search, index) still function

**Indexing not working?**
- Run `memsearch index .memsearch/memory/` manually to check for errors
- Check your memsearch config: `memsearch config list --resolved`
