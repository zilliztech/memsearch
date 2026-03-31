# memsearch OpenCode Plugin

Semantic memory search for [OpenCode](https://github.com/anomalyco/opencode) — gives your AI assistant persistent memory across sessions with zero user intervention.

## Features

- **Auto-capture**: Summarizes each conversation turn and saves to daily `.md` files
- **Semantic search**: Hybrid search (BM25 + dense vectors + RRF) via Milvus
- **Three-layer recall**: Search → Expand → Transcript (progressive detail)
- **Cold-start context**: Injects recent memories into new sessions automatically
- **Per-project isolation**: Each project gets its own Milvus collection
- **ONNX embeddings**: CPU-only bge-m3 model, no API key required

## Quick Start

### Prerequisites

```bash
# Install memsearch with ONNX embeddings
uv tool install 'memsearch[onnx]'
# or: pip install 'memsearch[onnx]'
```

### Install from npm (recommended)

```json
// In ~/.config/opencode/opencode.json
{
  "plugin": ["@zilliz/memsearch-opencode"]
}
```

### Install from Source (development)

```bash
# Clone the repo
git clone https://github.com/zilliztech/memsearch.git
cd memsearch

# Run the installer
bash plugins/opencode/install.sh
```

### Manual Install

```bash
# 1. Symlink the plugin
mkdir -p ~/.config/opencode/plugins
ln -sf /path/to/memsearch/plugins/opencode/index.ts ~/.config/opencode/plugins/memsearch.ts

# 2. Symlink the skill (optional, for !memory-recall)
mkdir -p ~/.agents/skills
ln -sf /path/to/memsearch/plugins/opencode/skills/memory-recall ~/.agents/skills/memory-recall
```

## Architecture

```
OpenCode Session
    ├── chat.message hook ──→ Detect turn completion
    │                              │
    │                              ├── Extract last turn from SQLite
    │                              ├── Summarize via LLM (third-person notes)
    │                              └── Append to .memsearch/memory/YYYY-MM-DD.md
    │                                     │
    │                                     └── memsearch index (background)
    │
    ├── system.transform hook ──→ Inject recent memories
    │
    └── Tools
        ├── memory_search ──→ memsearch search (hybrid BM25+dense)
        ├── memory_get    ──→ memsearch expand (full context)
        └── memory_transcript ──→ parse-transcript.py (SQLite reader)
```

## Recall Memories

**Manual invocation** — explicitly invoke the skill with a query:

```
/memory-recall what was the auth approach we discussed?
```

**Auto invocation** — just ask naturally, the LLM auto-invokes memory tools when it senses the question needs history:

```
We discussed the authentication flow before, what was the approach?
```

## Tools

| Tool | Description |
|------|-------------|
| `memory_search` | Semantic search over past memories. Returns ranked chunks. |
| `memory_get` | Expand a chunk hash to see the full markdown section. |
| `memory_transcript` | Read original conversation from OpenCode SQLite DB. |

## Memory Files

Memory is stored as markdown in `<project>/.memsearch/memory/`:

```
.memsearch/
└── memory/
    ├── 2026-03-25.md
    └── 2026-03-26.md
```

Each file contains timestamped entries with bullet-point summaries:

```markdown
# 2026-03-26

## Session 14:30

### 14:30
<!-- session:ses_abc123 db:~/.local/share/opencode/opencode.db -->
- User asked about the authentication flow.
- Assistant explained the OAuth2 implementation in auth.ts.
- Assistant modified the token refresh logic in refresh.ts.
```

## Configuration

The plugin uses ONNX embeddings by default (no API key needed). To use a different provider:

```bash
memsearch config set embedding.provider openai
# Set the API key in your environment
export OPENAI_API_KEY=sk-...
```

## How It Works

1. **Capture**: After each conversation turn, the plugin extracts the user+assistant exchange, summarizes it via LLM, and appends to a daily markdown file.

2. **Index**: The markdown files are indexed by memsearch into a Milvus collection (Milvus Lite by default, runs in-process).

3. **Recall**: When the assistant needs historical context, it calls `memory_search` to find relevant chunks. Results can be expanded with `memory_get` or drilled into with `memory_transcript`.

4. **Cold-start**: At session start, recent memory bullets are injected into the system prompt so the assistant has immediate context.

## Differences from Other Plugins

| Feature | Claude Code | OpenCode | OpenClaw |
|---------|-------------|----------|----------|
| Session storage | JSONL | SQLite | JSONL |
| Hook system | Shell scripts | TypeScript hooks | JS API |
| Summarizer | claude -p --model haiku | opencode prompt | openclaw agent |
| Context injection | SessionStart hook | system.transform | before_agent_start |
| Skill context | context: fork | N/A (no fork) | N/A |
