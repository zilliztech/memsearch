# Installation

## Install from Marketplace (recommended)

```bash
# 1. In Claude Code, add the marketplace and install the plugin
/plugin marketplace add zilliztech/memsearch
/plugin install memsearch

# 2. Restart Claude Code to activate the plugin (exit and reopen)

# 3. Have a conversation, then exit. Check your memories:
cat .memsearch/memory/$(date +%Y-%m-%d).md

# 4. Start a new session -- Claude automatically remembers!
```

## Install from Source (development)

```bash
git clone https://github.com/zilliztech/memsearch.git
cd memsearch && uv sync
claude --plugin-dir ./plugins/claude-code
```

!!! note "First-time ONNX model download"
    The plugin defaults to **ONNX bge-m3** embedding -- no API key required, runs locally on CPU. On first launch, the model (~558 MB) is downloaded from HuggingFace Hub. Pre-download it manually:

    ```bash
    uvx --from 'memsearch[onnx]' memsearch search --provider onnx "warmup" 2>/dev/null || true
    ```

    If the download is slow, set `export HF_ENDPOINT=https://hf-mirror.com` to use a mirror.

---

## Configuration

The plugin defaults to **ONNX bge-m3** embedding (no API key, CPU-only). To use a different provider:

```bash
memsearch config set embedding.provider openai
export OPENAI_API_KEY="sk-..."
```

For Milvus backend configuration, see [Getting Started -- Milvus Backends](../../getting-started.md#milvus-backends).

---

## Updating

Marketplace installs use Claude Code's plugin update commands:

```bash
# Refresh marketplace metadata, then update the installed plugin
claude plugin marketplace update memsearch-plugins
claude plugin update memsearch
```

Restart Claude Code after updating so the new hooks and skill files are loaded.

For source installs, pull the latest repo and restart Claude Code with the same plugin directory:

```bash
cd memsearch
git pull
uv sync
claude --plugin-dir ./plugins/claude-code
```

## Uninstall

```bash
claude plugin uninstall memsearch --keep-data
```

The uninstall command removes the Claude Code plugin integration. Your project memories under `.memsearch/memory/` are not deleted.
