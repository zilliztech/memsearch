# memsearch — OpenClaw Plugin

Automatic persistent memory for [OpenClaw](https://github.com/openclaw/openclaw). Every conversation turn is summarized and indexed — your next session picks up where you left off.

## Prerequisites

- [OpenClaw](https://github.com/openclaw/openclaw) >= 2026.3.22
- Python 3.10+

## Install

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

Different agents have separate Milvus collections (`ms_openclaw_main`, `ms_openclaw_work`), so memories never mix. The plugin reads `agentId` from the tool factory context and routes accordingly.

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
