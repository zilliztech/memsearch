# memsearch — OpenClaw Plugin

Automatic persistent memory for [OpenClaw](https://github.com/openclaw/openclaw). Every conversation turn is summarized and indexed — your next session picks up where you left off.

## Prerequisites

- [OpenClaw](https://github.com/openclaw/openclaw) >= 2026.3.22 (2026.4+ recommended for full CLI support)
- Python 3.10+

## Install

### From ClawHub (recommended)

```bash
# 1. Install memsearch
uv tool install "memsearch[onnx]"

# 2. Install the plugin from ClawHub
openclaw plugins install clawhub:memsearch

# 3. Restart the gateway
openclaw gateway restart
```

### From Source (development)

```bash
# 1. Install memsearch
uv tool install "memsearch[onnx]"

# 2. Clone the repo and install the plugin
git clone https://github.com/zilliztech/memsearch.git
cd memsearch
openclaw plugins install ./plugins/openclaw

# 3. Restart the gateway
openclaw gateway restart
```

## Usage

Start a TUI session as normal:

```bash
openclaw tui
```

### What happens automatically

| When | What |
|------|------|
| Agent starts | Recent memories injected as context |
| Each turn ends | Conversation summarized (bullet-points) and saved to daily `.md` |
| LLM needs history | Calls `memory_search` / `memory_get` / `memory_transcript` tools |

### Recall memories

Two ways to trigger:

```
/memory-recall what was the caching strategy we chose?
```
Or just ask naturally — the LLM auto-invokes memory tools when it senses the question needs history:
```
We discussed caching strategies before, what did we decide?
```

### Three-layer progressive recall

The plugin registers three tools the LLM uses progressively:

1. **`memory_search`** — Semantic search across past memories. Always starts here.
2. **`memory_get`** — Expand a chunk to see the full markdown section with context.
3. **`memory_transcript`** — Parse the original session transcript for exact dialogue.

The LLM decides how deep to go based on the question — simple recall uses only L1, detailed questions go to L2/L3.

### Multi-agent isolation

Each OpenClaw agent stores memory independently under its own workspace:

```
~/.openclaw/workspace/.memsearch/memory/          ← main agent
~/.openclaw/workspace-work/.memsearch/memory/      ← work agent
```

Collection names are derived from the workspace path (same algorithm as Claude Code, Codex, and OpenCode), so agents with different workspaces have isolated memories. When an agent's workspace points to a project directory used by other platforms, memories are automatically shared across platforms.

## Configuration

Works out of the box with zero configuration (ONNX embedding, no API key needed).

Optional settings via `openclaw plugins config memsearch`:

| Setting | Default | Description |
|---------|---------|-------------|
| `provider` | `onnx` | Embedding provider (onnx, openai, google, voyage, ollama) |
| `autoCapture` | `true` | Auto-capture conversation summaries after each turn |
| `autoRecall` | `true` | Auto-inject recent memories at agent start |

## Memory files

Each agent's memory is stored as plain markdown:

```markdown
# 2026-03-25

## Session 14:47

### 14:47
<!-- session:UUID transcript:~/.openclaw/agents/main/sessions/UUID.jsonl -->
- User asked about the memsearch architecture.
- OpenClaw explained core components: chunker, scanner, embedder, MilvusStore.
```

These files are human-readable, editable, and version-controllable. Milvus is a derived index that can be rebuilt anytime.

## Uninstall

```bash
openclaw plugins install --remove memsearch
# Or manually:
rm -rf ~/.openclaw/extensions/memsearch
```
