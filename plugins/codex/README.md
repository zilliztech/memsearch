# memsearch — Codex CLI Plugin

Automatic persistent memory for [Codex CLI](https://github.com/openai/codex). Every conversation turn is summarized and indexed — your next session picks up where you left off.

## Prerequisites

- [Codex CLI](https://github.com/openai/codex) v0.116.0+
- Python 3.10+

## Install

```bash
# 1. Install memsearch
uv tool install "memsearch[onnx]"

# 2. Clone the repo and run the installer
git clone https://github.com/zilliztech/memsearch.git
cd memsearch
bash plugins/codex/scripts/install.sh
```

The installer sets up everything automatically:
- Copies the **memory-recall** skill to `~/.agents/skills/`
- Generates `~/.codex/hooks.json` with the correct hook paths
- Enables the `codex_hooks` feature flag

## Usage

Start Codex with `--yolo` to allow memsearch full access (network + filesystem):

```bash
codex --yolo
```

> **Why `--yolo`?** The ONNX embedding model needs network on first run to download from HuggingFace (~100 MB). After that it's cached locally. Codex's default sandbox blocks network, which prevents model download and Milvus Lite file access. `--yolo` disables the sandbox — equivalent to Claude Code's `--dangerously-skip-permissions`.

**Pre-cache the model** (optional) — run once so subsequent sessions work even without `--yolo`:

```bash
memsearch search "test" --collection test_warmup 2>/dev/null; memsearch reset --collection test_warmup --yes 2>/dev/null
```

### What happens automatically

| When | What |
|------|------|
| Session starts | Recent memory context is injected; you'll see `[memsearch v...]` in the status line |
| Each prompt | A `[memsearch] Memory available` hint reminds Codex that memory-recall is available |
| Each turn ends | The conversation is summarized and saved to a daily `.md` file |

### Search past memories

Use the `$memory-recall` skill:

```
$memory-recall what did we discuss about batch size limits?
```

Codex will search your memory, expand relevant results, and return a curated summary. The skill uses three-layer progressive disclosure:

1. **Search** — `memsearch search` finds relevant chunks by semantic + keyword hybrid search
2. **Expand** — `memsearch expand` retrieves the full markdown section around a match
3. **Deep drill** — optionally parses the original Codex rollout transcript for exact conversation context

## Configuration

### Embedding provider

Default is `onnx` (bge-m3) — runs locally, no API key needed.

```bash
# Switch to OpenAI embeddings (requires OPENAI_API_KEY)
memsearch config set embedding.provider openai

# Switch back to local ONNX
memsearch config set embedding.provider onnx
```

### Milvus backend

Default is Milvus Lite (local `.db` file). For larger memory stores or team sharing:

```bash
# Use a remote Milvus server
memsearch config set milvus.uri http://localhost:19530
```

## Memory files

Each project stores memory under `<project>/.memsearch/memory/`:

```
.memsearch/memory/
├── 2026-03-20.md
├── 2026-03-21.md
└── 2026-03-24.md
```

These are plain markdown files — human-readable, editable, and version-controllable. Milvus is a derived index that can be rebuilt anytime from these files.

## Uninstall

```bash
rm -rf ~/.agents/skills/memory-recall
rm ~/.codex/hooks.json
# Optionally remove the feature flag from ~/.codex/config.toml
```

## Updating

```bash
cd memsearch
git pull
bash plugins/codex/scripts/install.sh
```
