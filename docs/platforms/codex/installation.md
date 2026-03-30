# Installation

## Prerequisites

- Codex CLI v0.116.0+
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

## Install

```bash
# 1. Clone the memsearch repo (if not already)
git clone https://github.com/zilliztech/memsearch.git

# 2. Run the installer
bash memsearch/plugins/codex/scripts/install.sh
```

The installer:

1. Copies the memory-recall skill to `~/.agents/skills/`
2. Generates `~/.codex/hooks.json` with memsearch hooks
3. Enables `codex_hooks = true` in `~/.codex/config.toml`
4. Makes all scripts executable

## Usage

```bash
codex --yolo
```

!!! warning "Why `--yolo`?"
    Codex needs `--yolo` mode on the first run because the ONNX embedding model downloads from HuggingFace Hub (network access required). After the model is cached, `--yolo` is still needed because hooks execute shell commands.

## Pre-cache the Model (optional)

```bash
memsearch search "test" --collection test_warmup --provider onnx 2>/dev/null || true
```

---

## Configuration

### Embedding Provider

Default: `onnx` (bge-m3, CPU, no API key). Change with:

```bash
memsearch config set embedding.provider openai
export OPENAI_API_KEY="sk-..."
```

### Milvus Backend

Default: Milvus Lite (`~/.memsearch/milvus.db`). For remote Milvus:

```bash
memsearch config set milvus.uri http://localhost:19530
```

---

## Uninstall

```bash
# Remove hooks
rm ~/.codex/hooks.json

# Remove skill
rm -rf ~/.agents/skills/memory-recall

# Disable hooks in config
# Edit ~/.codex/config.toml and set codex_hooks = false

# Optionally remove memsearch
uv tool uninstall memsearch
```

## Updating

```bash
# Update memsearch
uv tool upgrade memsearch

# Re-run installer to update hooks and skill
bash memsearch/plugins/codex/scripts/install.sh
```
