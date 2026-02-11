# 🧠 memsearch — Claude Code Plugin

**Automatic persistent memory for Claude Code.** No commands to learn, no manual saving — just install the plugin and Claude remembers what you worked on across sessions.

```bash
# In Claude Code:
/plugin marketplace add zilliztech/memsearch
/plugin install memsearch@memsearch
```

## 💡 Design Principles

memsearch follows two core philosophies:

**🔧 Native to Claude Code** — built entirely on Claude Code's own primitives: **Hooks** for lifecycle events, **CLI** for tool access, and **Agent** for autonomous decisions. No MCP servers, no sidecar services, no extra network round-trips. Everything runs locally as shell scripts and a Python CLI, keeping latency low and context window clean.

**📝 Markdown as single source of truth** — the same architecture that powers [OpenClaw's memory system](https://docs.openclaw.ai/concepts/memory). All knowledge lives in plain `.md` files — human-readable, `git`-friendly, trivially portable. The vector index (Milvus) is a **derived cache** that can be rebuilt from markdown at any time. No opaque databases, no binary blobs, no vendor lock-in.

The result: a memory system that's **simple enough to understand in 5 minutes**, yet powerful enough for production use with hybrid search (dense + BM25) and three-layer progressive disclosure.

## 🚀 Quick Start

### Install from Marketplace (recommended)

```bash
# 1. Install the memsearch CLI
pip install memsearch

# 2. (Optional) Initialize config
memsearch config init

# 3. In Claude Code, add the marketplace and install the plugin
/plugin marketplace add zilliztech/memsearch
/plugin install memsearch@memsearch

# 4. Have a conversation, then exit. Check your memories:
cat .memsearch/memory/$(date +%Y-%m-%d).md

# 5. Start a new session — Claude remembers!
```

### Development mode

For contributors or if you want to modify the plugin:

```bash
git clone https://github.com/zilliztech/memsearch.git
pip install memsearch
claude --plugin-dir ./memsearch/ccplugin
```

## ⚙️ How It Works

The plugin hooks into 4 Claude Code lifecycle events. A singleton `memsearch watch` process keeps the vector index in sync with markdown files in the background.

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                  🔄 memsearch plugin lifecycle                         │
  └─────────────────────────────────────────────────────────────────────────┘

  🟢 SESSION START
  ─────────────
  ┌──────────────┐     ┌─────────────────┐     ┌──────────────────────────┐
  │ SessionStart │────▶│ Start singleton │────▶│ Write session heading    │
  │   hook       │     │ memsearch watch │     │ to today's memory .md    │
  └──────────────┘     │ (PID file lock) │     └──────────────────────────┘
                       └─────────────────┘              │
                              │                         ▼
                              ▼                  ┌──────────────────────────┐
                       ┌─────────────────┐       │ Inject recent memories + │
                       │ watch monitors  │       │ Memory Tools instructions│
                       │ .memsearch/     │       │ { "additionalContext" }  │
                       │   memory/*.md   │       └──────────────────────────┘
                       └─────────────────┘
                       (background, 1500ms debounce, auto-sync on change)

  💬 EVERY USER PROMPT
  ─────────────────
  ┌──────────────────┐     ┌─────────────────┐     ┌────────────────────┐
  │ UserPromptSubmit │────▶│ memsearch search │────▶│ Inject top-3       │
  │   hook           │     │ "$user_prompt"   │     │ relevant memories  │
  └──────────────────┘     │ --top-k 3        │     │ + chunk_hash IDs   │
                           └─────────────────┘     └────────────────────┘
                           (skip if < 10 chars)

  🛑 WHEN CLAUDE FINISHES RESPONDING
  ────────────────────────────────
  ┌──────────┐     ┌──────────────────────┐     ┌──────────────────────┐
  │  Stop    │────▶│ parse-transcript.sh  │────▶│ claude -p --model    │
  │(command, │     │ (truncate + format)  │     │ haiku summarizes     │
  │  async)  │     └──────────────────────┘     └──────────────────────┘
  └──────────┘                                    │
                                                  ▼
                                           ┌──────────────────────┐
                                           │ Append summary with  │
                                           │ session/turn anchors │
                                           │ to YYYY-MM-DD.md     │
                                           └──────────────────────┘
                                                  │
                                                  └──▶ watch detects change
                                                       → auto-sync

  👋 SESSION END
  ───────────
  ┌──────────────┐
  │ SessionEnd   │──── stop watch process (cleanup)
  └──────────────┘
```

### 🪝 Hook Summary

| Hook | Type | What it does |
|------|------|-------------|
| **SessionStart** | command | Start `memsearch watch` singleton + write session heading + inject recent memories & Memory Tools |
| **UserPromptSubmit** | command | Semantic search on user prompt → inject relevant memories with `chunk_hash` |
| **Stop** | command (async) | Parse transcript → `claude -p --model haiku` summary → write to daily `.md` with session anchors |
| **SessionEnd** | command | Stop the `memsearch watch` process |

## 🔍 Progressive Disclosure

Memory retrieval uses a three-layer progressive disclosure model. The main Claude agent decides when to drill deeper.

```
  L1: 📋 Auto-injected (UserPromptSubmit hook)
  ──────────────────────────────────────────
  Every prompt → top-k search results with chunk_hash + 200-char preview

  L2: 📖 On-demand expand (memsearch expand)
  ──────────────────────────────────────────
  Agent runs: memsearch expand <chunk_hash>
  → Full markdown section + session/turn anchor metadata

  L3: 💬 Transcript drill-down (memsearch transcript)
  ──────────────────────────────────────────
  Agent runs: memsearch transcript <jsonl_path> --turn <uuid> --context 3
  → Original conversation turns from the JSONL transcript
```

Each memory summary includes an HTML comment anchor:
```markdown
### 14:30
<!-- session:abc123 turn:def456 transcript:/path/to/session.jsonl -->
- Implemented caching system with Redis L1 and in-process LRU L2
```

The anchor links the chunk back to its source session, enabling L2→L3 drill-down.

## 📁 Memory Storage

All memories live in **`.memsearch/memory/`** inside your project directory:

```
your-project/
└── .memsearch/
    ├── .watch.pid        ← singleton watcher PID
    └── memory/
        ├── 2026-02-07.md
        ├── 2026-02-08.md
        └── 2026-02-09.md    ← today's session summaries
```

Each file contains session summaries in plain markdown:

```markdown
## Session 14:30

### 14:30
<!-- session:abc123 turn:def456 transcript:/home/user/.claude/projects/.../abc123.jsonl -->
- Implemented caching system with Redis L1 and in-process LRU L2
- Fixed N+1 query issue in order-service using selectinload
- Decided to use Prometheus counters for cache hit/miss metrics

## Session 17:45

### 17:45
<!-- session:ghi789 turn:jkl012 transcript:/home/user/.claude/projects/.../ghi789.jsonl -->
- Debugged React hydration mismatch — Date.now() during SSR
- Added comprehensive test suite for the caching middleware
```

**📝 Markdown is the source of truth.** The Milvus vector index is a derived cache that can be rebuilt at any time with `memsearch index .memsearch/memory/`.

## ⚖️ memsearch vs claude-mem

| | 🧠 memsearch | claude-mem |
|---|---|---|
| **Architecture** | 🪶 4 shell hooks + 1 watch process — that's it | Node.js/Bun Worker service + Express server + React UI |
| **Integration** | 🔧 Native hooks + CLI — zero IPC overhead | MCP server (stdio) — tool definitions permanently consume context window |
| **Memory recall** | ✅ **Automatic** — semantic search on every prompt via hook | 🔧 **Agent-driven** — Claude must explicitly call MCP `search` tool |
| **Progressive disclosure** | 🔍 **3-layer, auto-triggered**: hook injects top-k → `expand` → `transcript` drill-down | 🔍 **3-layer, all manual**: `search` → `timeline` → `get_observations` (all require explicit tool calls) |
| **Session summary** | 💰 `claude -p --model haiku` — one cheap call, runs async | 💸 Observation on every tool use + session summary — more API calls at scale |
| **Vector backend** | 🚀 **Milvus** — hybrid search (dense + BM25), scales from embedded to distributed cluster | Chroma — dense only, limited scaling path |
| **Storage format** | 📝 Transparent `.md` files — human-readable, git-friendly | Opaque SQLite + Chroma binary |
| **Index sync** | 🔄 `memsearch watch` singleton — auto-debounced background sync | Automatic observation writes via hooks, but no unified background sync |
| **Data portability** | 📦 Copy `.memsearch/memory/*.md` — done | Export from SQLite + Chroma |
| **Runtime dependency** | Python (`memsearch` CLI) + `claude` CLI | Node.js + Bun + MCP runtime |
| **Context window cost** | 🪶 Minimal — hook injects only top-k results as plain text | 🏋️ MCP tool definitions always loaded + each tool call/result consumes context |
| **Cost per session** | 💵 ~1 Haiku call for summary | 💸 Multiple Claude API calls for observation compression |

### 🏗️ Key design differences

The fundamental difference is **automatic vs agent-driven** memory recall:

**memsearch** injects relevant memories into **every prompt** via hooks — Claude doesn't need to decide whether to search, it just gets the context. Progressive disclosure starts automatically (L1 via hook), and only deeper layers (L2 expand, L3 transcript) require explicit CLI calls. The architecture is **lightweight by design**: shell hooks → CLI → markdown → Milvus. No MCP servers consuming context window, no background services requiring ports, no opaque binary databases. The entire system is auditable by reading a handful of shell scripts and `.md` files.

**claude-mem** gives Claude **MCP tools** to search, explore timelines, and fetch full observations — a 3-layer system as well, but all three layers require Claude to **proactively decide** to invoke them. This is more flexible (Claude controls when and what to recall) but means memories are only retrieved when Claude thinks to ask, and MCP tool definitions permanently occupy context window space. The full-stack architecture (Worker service + SQLite + Chroma + React UI) offers richer features like a web viewer, but with significant complexity cost.

## 📂 Plugin Files

```
ccplugin/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
└── hooks/
    ├── hooks.json               # Hook definitions (4 hooks)
    ├── common.sh                # Shared setup: env, PATH, memsearch detection, watch management
    ├── session-start.sh         # Start watch + write session heading + inject memories & tools
    ├── user-prompt-submit.sh    # Semantic search on prompt → inject memories with chunk_hash
    ├── stop.sh                  # Parse transcript → haiku summary → append to daily .md
    ├── parse-transcript.sh      # Deterministic JSONL→text parser with truncation
    └── session-end.sh           # Stop watch process
```

## 🛠️ The `memsearch` CLI

This plugin is built entirely on the [`memsearch`](../README.md) CLI — every hook is just a shell script calling `memsearch` subcommands. Here's what's available:

| Command | Used by | What it does |
|---------|---------|-------------|
| `search <query>` | UserPromptSubmit hook | Semantic search over indexed memories (`-k` for top-K, `-j` for JSON) |
| `watch <paths>` | SessionStart hook | Background watcher that auto-indexes on file changes (debounced) |
| `index <paths>` | Manual / rebuild | One-shot index of markdown files (`--force` to re-index all) |
| `expand <chunk_hash>` | Agent (L2 disclosure) | Show full markdown section around a chunk, with anchor metadata |
| `transcript <jsonl>` | Agent (L3 disclosure) | Parse Claude Code JSONL transcript into readable conversation turns |
| `compact` | Manual | LLM-powered compression of old memories into summaries |
| `config init\|list\|get\|set` | Quick Start | Interactive config wizard, view/modify settings |
| `stats` | Manual | Show index statistics (collection size, chunk count) |
| `reset` | Manual | Drop all indexed data (requires `--yes` to confirm) |

The progressive disclosure commands (`expand` and `transcript`) are the main interaction point for the Claude agent — details below.

### `memsearch expand <chunk_hash>`

Look up a chunk by hash in the Milvus index and display the full markdown section around it.

```bash
# Show full section
memsearch expand abc123def456

# JSON output with anchor metadata (session/turn/transcript path)
memsearch expand abc123def456 --json-output

# Show N lines before/after instead of full section
memsearch expand abc123def456 --lines 10
```

### `memsearch transcript <jsonl_path>`

Parse a Claude Code JSONL transcript and display conversation turns.

```bash
# Show index of all turns
memsearch transcript /path/to/session.jsonl

# Show context around a specific turn (prefix match on UUID)
memsearch transcript /path/to/session.jsonl --turn bffc0c1b --context 3

# JSON output
memsearch transcript /path/to/session.jsonl --turn bffc0c1b --json-output
```

