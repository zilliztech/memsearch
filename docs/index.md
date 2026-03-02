# memsearch

**OpenClaw's memory, everywhere.**

> Inspired by [OpenClaw](https://github.com/openclaw/openclaw)'s memory system, memsearch brings the same markdown-first architecture to a standalone library. Pluggable into *any* agent framework, backed by [Milvus](https://milvus.io/).

---

## Why memsearch?

```bash
$ cat /dev/philosophy
Markdown is the source of truth.
Simple. Readable. Git-friendly. Zero vendor lock-in.
The vector store is just a derived index — rebuildable anytime.
```

Most memory systems treat the vector database as the source of truth. memsearch flips this around: **your markdown files are the canonical data store**, and the vector store is just a derived index -- like a database index that can be dropped and rebuilt at any time.

This means:

- **Your data is always human-readable** -- plain `.md` files you can open, edit, grep, and `git diff`
- **No vendor lock-in** -- switch embedding providers or vector backends without losing anything
- **Rebuild on demand** -- corrupted index? Just re-run `memsearch index` and you are back in seconds
- **Git-native** -- version your knowledge base with standard git workflows

---

## Key Features

- **Markdown is the source of truth** -- human-readable, `git`-friendly, zero vendor lock-in
- **Smart dedup** -- SHA-256 content hashing means unchanged content is never re-embedded
- **Hybrid search** -- dense vector (cosine) + BM25 full-text with RRF reranking
- **Live sync** -- file watcher auto-indexes changes, deletes stale chunks
- **Memory compact** -- LLM-powered summarization compresses old memories
- **[Ready-made Claude Code plugin](claude-plugin/index.md)** -- a drop-in example of agent memory built on memsearch

---

## Quick Start

```bash
pip install memsearch
```

```python
from memsearch import MemSearch

mem = MemSearch(paths=["./memory"])

await mem.index()                                      # index markdown files
results = await mem.search("Redis config", top_k=3)    # semantic search
print(results[0]["content"], results[0]["score"])       # content + similarity
```

```bash
memsearch index ./memory/
memsearch search "how to configure Redis?"
```

See [Getting Started](getting-started.md) for a complete walkthrough including agent memory loops, API key setup, and Milvus backend options.

---

## Use Cases

### Personal Knowledge Base

Point memsearch at your notes directory and get instant semantic search across years of accumulated knowledge.

```bash
memsearch index ~/notes/
memsearch search "that article about distributed consensus"
```

### Agent Memory

Give your AI agent persistent, searchable memory. The agent writes observations to markdown files; memsearch indexes them and retrieves relevant context on the next turn. This is exactly how [OpenClaw](https://github.com/openclaw/openclaw) manages memory, and memsearch ships with a ready-made [Claude Code plugin](claude-plugin/index.md) that demonstrates the pattern.

### Team Knowledge Sharing

Deploy a shared Milvus server and point multiple team members (or agents) at it. Everyone indexes their own markdown files into the same collection, creating a shared searchable knowledge base.

---

## Embedding Providers

memsearch supports **5 embedding providers** -- from cloud APIs to fully local models with no API key required:

| Provider | Install | API Key |
|----------|---------|---------|
| OpenAI (default) | `pip install memsearch` | `OPENAI_API_KEY` |
| Google Gemini | `pip install "memsearch[google]"` | `GOOGLE_API_KEY` |
| Voyage AI | `pip install "memsearch[voyage]"` | `VOYAGE_API_KEY` |
| Ollama (local) | `pip install "memsearch[ollama]"` | none |
| sentence-transformers (local) | `pip install "memsearch[local]"` | none |

For zero-config local operation with no API keys, install `memsearch[local]` or `memsearch[ollama]`. See [CLI Reference -- Embedding Provider Reference](cli.md#embedding-provider-reference) for model details and dimensions.

---

## Milvus Backends

Just change the URI to switch backends -- no other code changes needed:

| Mode | URI | Platform |
|------|-----|----------|
| **Milvus Lite** (default) | `~/.memsearch/milvus.db` | Linux, macOS |
| **Milvus Server** | `http://localhost:19530` | All (via Docker) |
| **Zilliz Cloud** | `https://in03-xxx.zillizcloud.com` | All (managed) |

!!! warning "Windows"
    Milvus Lite does not provide Windows binaries. On Windows use Milvus Server (Docker) or Zilliz Cloud. See [FAQ -- Does memsearch work on Windows?](faq.md#does-memsearch-work-on-windows)

See [Getting Started -- Milvus Backends](getting-started.md#milvus-backends) for connection examples and Docker setup.

---

## Next Steps

- **[Getting Started](getting-started.md)** -- installation, configuration, and your first memory search
- **[Python API](python-api.md)** -- full reference for the `MemSearch` class
- **[CLI Reference](cli.md)** -- complete reference for all `memsearch` commands
- **[Architecture](architecture.md)** -- deep dive into chunking, dedup, and hybrid search
- **[Integrations](integrations.md)** -- LangChain, LangGraph, LlamaIndex, CrewAI
- **[Claude Code Plugin](claude-plugin/index.md)** -- give Claude automatic persistent memory across sessions
- **[FAQ & Troubleshooting](faq.md)** -- common questions and error fixes

---

## License

MIT
