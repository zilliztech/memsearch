# Configuration

memsearch uses a layered TOML config system. Most users don't need to configure anything — the defaults work out of the box.

## Config Locations (priority low → high)

1. `~/.memsearch/config.toml` — global defaults
2. `<project>/.memsearch.toml` — project-level overrides
3. CLI flags — highest priority

## Quick Setup

```bash
# Interactive config wizard
memsearch config init

# Or set individual values
memsearch config set embedding.provider onnx
memsearch config set milvus.uri http://localhost:19530
```

## Embedding Provider

| Provider | Install | API Key | Notes |
|----------|---------|---------|-------|
| **onnx** (default) | `pip install memsearch[onnx]` | No | Local, free, ~100MB model download |
| openai | `pip install memsearch[openai]` | `OPENAI_API_KEY` | Best quality |
| google | `pip install memsearch[google]` | `GOOGLE_API_KEY` | Gemini embeddings |
| voyage | `pip install memsearch[voyage]` | `VOYAGE_API_KEY` | High quality |
| ollama | `pip install memsearch[ollama]` | No | Local, any model |

```bash
# Switch provider
memsearch config set embedding.provider openai
memsearch index --force   # re-index with new provider
```

## Milvus Backend

| Backend | Config | Notes |
|---------|--------|-------|
| **Milvus Lite** (default) | `~/.memsearch/milvus.db` | Single-file, zero setup |
| Milvus Server | `http://localhost:19530` | Docker, production-grade |
| [Zilliz Cloud](https://cloud.zilliz.com) | `https://xxx.zillizcloud.com` | Managed, no ops |

```bash
# Switch to remote Milvus
memsearch config set milvus.uri http://localhost:19530

# Use Zilliz Cloud
memsearch config set milvus.uri "https://xxx.api.gcp-us-west1.zillizcloud.com"
memsearch config set milvus.token "your-token"
```

## View Current Config

```bash
memsearch config list          # show all settings
memsearch config get milvus.uri  # show specific value
```

## Platform-Specific Config

Each plugin may have additional configuration. See:

- [Claude Code Plugin](../platforms/claude-code.md)
- [OpenClaw Plugin](../platforms/openclaw.md)
- [OpenCode Plugin](../platforms/opencode.md)
- [Codex CLI Plugin](../platforms/codex.md)
