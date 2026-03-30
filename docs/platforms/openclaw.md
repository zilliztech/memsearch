# OpenClaw Plugin

**Semantic memory for [OpenClaw](https://github.com/openclaw/openclaw) agents.** A TypeScript plugin with `kind: memory` that replaces OpenClaw's built-in memory-core with hybrid semantic search.

---

## Quick Start

### Prerequisites

- OpenClaw >= 2026.3.22
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

### Installation

```bash
# 1. Clone the memsearch repo (if not already)
git clone https://github.com/zilliztech/memsearch.git

# 2. Install the OpenClaw plugin
openclaw plugins install ./memsearch/plugins/openclaw

# 3. Restart the gateway
openclaw gateway restart
```

### Usage

Start a TUI session as normal -- memory is captured and recalled automatically.

---

## What Happens Automatically

| Event | What memsearch does |
|-------|-------------------|
| **Agent starts** | Recent memories from the 2 most recent daily logs are injected as context |
| **Each turn ends** | Conversation is summarized by the OpenClaw agent and appended to daily `.md` |
| **LLM needs history** | Calls `memory_search`, `memory_get`, or `memory_transcript` tools progressively |

---

## Tools

The plugin registers three tools via `registerTool`:

| Tool | Parameters | What it does |
|------|-----------|-------------|
| `memory_search` | `query`, `top_k` | Semantic search over indexed memories via `memsearch search` |
| `memory_get` | `chunk_hash` | Expand a chunk to full markdown section via `memsearch expand` |
| `memory_transcript` | `transcript_path` | Parse original session transcript for verbatim recall |

### Three-Layer Progressive Recall

| Layer | Tool | What it returns |
|-------|------|----------------|
| **L1: Search** | `memory_search` | Top-K relevant chunk snippets |
| **L2: Expand** | `memory_get` | Full markdown section around a chunk |
| **L3: Transcript** | `memory_transcript` | Original conversation from OpenClaw JSONL |

The LLM autonomously decides which layers to use based on the query.

---

## Multi-Agent Isolation

OpenClaw supports multiple agents (e.g., `main`, `work`). The plugin provides per-agent memory isolation:

- Each agent gets its own memory directory: `~/.openclaw/workspace/.memsearch/`, `~/.openclaw/workspace-work/.memsearch/`
- Each agent gets its own Milvus collection: `ms_openclaw_main`, `ms_openclaw_work`
- The `agentId` from the tool factory context drives isolation -- no configuration needed

---

## Capture

The plugin hooks into OpenClaw's `llm_output` event with debounce. After each LLM response:

1. The conversation turn is extracted
2. The OpenClaw agent summarizes it as third-person bullet points
3. The summary is appended to `.memsearch/memory/YYYY-MM-DD.md` with session anchors
4. `memsearch index` re-indexes immediately

A fallback `agent_end` hook captures any turns missed in non-interactive mode.

---

## Cold-Start Context

On agent start (`before_agent_start` hook), the plugin reads the last 30 lines from the 2 most recent daily memory files and injects them as context. This gives the LLM awareness of recent sessions so it can decide when to use the memory tools.

---

## Memory Files

```
~/.openclaw/workspace/.memsearch/memory/
├── 2026-03-24.md
└── 2026-03-25.md
```

Example:

```markdown
# 2026-03-25

## Session 14:47

### 14:47
<!-- session:UUID transcript:~/.openclaw/agents/main/sessions/UUID.jsonl -->
- User asked about memsearch architecture
- Agent explained: chunker, scanner, embedder, MilvusStore
- Decided to use ONNX embedding for zero-config setup
```

---

## Configuration

```bash
openclaw plugins config memsearch
```

| Setting | Default | Description |
|---------|---------|-------------|
| `provider` | `onnx` | Embedding provider |
| `autoCapture` | `true` | Auto-capture conversations |
| `autoRecall` | `true` | Auto-inject recent memories on agent start |

For Milvus backend configuration, run `memsearch config set milvus.uri <uri>`.

---

## Plugin Files

```
plugins/openclaw/
├── package.json                    # npm package
├── openclaw.plugin.json            # Plugin config schema (kind: memory)
├── index.ts                        # Main plugin: tools, hooks, helpers
├── install.sh                      # Installation script
├── skills/
│   └── memory-recall/
│       └── SKILL.md                # Decision guide for memory tools
└── scripts/
    ├── derive-collection.sh        # Per-agent collection name
    └── parse-transcript.sh         # OpenClaw JSONL transcript parser
```

---

## Uninstall

```bash
openclaw plugins uninstall memsearch
openclaw gateway restart
```
