# Installation

## Prerequisites

- ZCode with hook support enabled
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

## Install

ZCode plugins are installed from a marketplace. The memsearch marketplace entry is defined in `.claude-plugin/marketplace.json` at the repository root.

### Option 1: Marketplace install (recommended)

1. Add the memsearch marketplace in ZCode's Discover tab (use the `+` button, not direct file editing -- `known_marketplaces.json` is reset on restart otherwise).
2. Install the `memsearch-zcode` plugin from the marketplace.
3. Enable the plugin in ZCode's plugin settings.

### Option 2: Source install

```bash
# 1. Clone the memsearch repo (if not already)
git clone https://github.com/zilliztech/memsearch.git

# 2. Install memsearch CLI
uv tool install "memsearch[onnx]"

# 3. Point ZCode at the plugin directory
#    In ZCode's plugin settings, add the marketplace from the cloned repo's
#    .claude-plugin/marketplace.json, then install memsearch-zcode.
```

The plugin's `hooks/hooks.json` uses `${CLAUDE_PLUGIN_ROOT}` to resolve hook
script paths, so ZCode handles the path resolution automatically after install.

## Usage

```bash
zcode
```

ZCode will fire the memsearch hooks on session start, each prompt submission, and each turn end. No special flags are required.

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

### Summarization

Default: `claude -p --model haiku` (same native path as the Claude Code plugin). Override:

```bash
# Use a different model for the native summarizer
memsearch config set plugins.zcode.summarize.model sonnet

# Route through a memsearch-managed API provider instead
memsearch config set llm.providers.anthropic.type anthropic
memsearch config set llm.providers.anthropic.model claude-sonnet-4-6
memsearch config set llm.providers.anthropic.api_key env:ANTHROPIC_API_KEY
memsearch config set plugins.zcode.summarize.provider anthropic
```

---

## Uninstall

Disable or remove the `memsearch-zcode` plugin in ZCode's plugin settings. This removes the hooks. To clean up fully:

```bash
# Optionally remove memsearch itself
uv tool uninstall memsearch
```

This removes the memsearch hooks and CLI. It does not delete project memory files in `.memsearch/memory/`.

## Updating

```bash
# Update memsearch with the ONNX extra preserved
uv tool install -U "memsearch[onnx]"

# Update the plugin from source
cd memsearch && git pull
# Re-install via marketplace if the version changed.
```
