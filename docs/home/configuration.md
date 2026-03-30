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
**Milvus Lite** (default) — zero config, single file. Great for getting started:

```bash
# Works out of the box, no setup needed
memsearch config get milvus.uri   # → ~/.memsearch/milvus.db
```

⭐ **Zilliz Cloud** (recommended) — fully managed, [free tier available](https://cloud.zilliz.com/signup?utm_source=github&utm_medium=referral&utm_campaign=memsearch-docs). No Docker, no ops. Concurrent access and real-time indexing:

```bash
memsearch config set milvus.uri "https://in03-xxx.api.gcp-us-west1.zillizcloud.com"
memsearch config set milvus.token "your-api-key"
```

??? note "Sign up for a free Zilliz Cloud cluster"
    You can [sign up](https://cloud.zilliz.com/signup?utm_source=github&utm_medium=referral&utm_campaign=memsearch-docs) on Zilliz Cloud to get a free cluster and API key.

    ![Sign up and get API key](https://raw.githubusercontent.com/zilliztech/CodeIndexer/master/assets/signup_and_get_apikey.png)

??? note "Self-hosted Milvus Server (Docker) — for advanced users"
    For multi-user or team environments. Requires Docker. See the [official installation guide](https://milvus.io/docs/install_standalone-docker-compose.md).

    ```bash
    memsearch config set milvus.uri http://localhost:19530
    ```

## View Current Config

```bash
memsearch config list          # show all settings
memsearch config get milvus.uri  # show specific value
```

## Platform-Specific Config

Each plugin may have additional configuration. See:

- [Claude Code Plugin](../platforms/claude-code/index.md)
- [OpenClaw Plugin](../platforms/openclaw/index.md)
- [OpenCode Plugin](../platforms/opencode/index.md)
- [Codex CLI Plugin](../platforms/codex/index.md)
