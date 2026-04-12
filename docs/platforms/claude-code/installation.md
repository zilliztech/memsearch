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

## Migration note: duplicate command entries

If Claude Code completion shows both plain commands like `/session-recall` and namespaced plugin entries like `(memsearch) /session-recall`, you likely still have an older standalone memsearch skill install under `~/.claude/skills/` in addition to the plugin install.

Recommended migration path:

1. Prefer the plugin/namespaced command form during migration so you are definitely invoking the plugin-provided skill.
2. After verifying the plugin install works, remove or archive only the legacy memsearch standalone skill paths under `~/.claude/skills/`.
3. Restart Claude Code so completion refreshes.

Do not treat this as two plugin copies in the source repo. It is typically a local install-state duplication between legacy standalone skills and the current plugin install.
