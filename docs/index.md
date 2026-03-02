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

- **OpenClaw's memory, everywhere** — markdown as the single source of truth
- **Smart dedup** — SHA-256 content hashing means unchanged content is never re-embedded
- **Live sync** — file watcher auto-indexes on changes, deletes stale chunks
- **Memory compact** — LLM-powered summarization compresses old memories
- **[Ready-made Claude Code plugin](claude-plugin.md)** — a drop-in example of agent memory built on memsearch

---

## What is memsearch?

Most memory systems treat the vector database as the source of truth. memsearch flips this around: **your markdown files are the source of truth**, and the vector store is just a derived index -- like a database index that can be dropped and rebuilt at any time.

This means:

- **Your data is always human-readable** — plain `.md` files you can open, edit, grep, and `git diff`
- **No vendor lock-in** — switch embedding providers or vector backends without losing anything
- **Rebuild on demand** — corrupted index? Just re-run `memsearch index` and you are back in seconds
- **Git-native** — version your knowledge base with standard git workflows

---

## Quick Install

```bash
$ pip install memsearch
```

Say you have a directory of daily markdown logs (the same layout used by OpenClaw):

```
memory/
├── MEMORY.md          # persistent facts & decisions
├── 2026-02-07.md      # daily log
├── 2026-02-08.md
└── 2026-02-09.md
```

Index it and search:

```bash
$ memsearch index ./memory/
Indexed 38 chunks.

$ memsearch search "how to configure Redis?"

--- Result 1 (score: 0.0328) ---
Source: memory/2026-02-08.md
Heading: Infrastructure Decisions
We chose Redis for caching over Memcached. Config: host=localhost,
port=6379, max_memory=256mb, eviction=allkeys-lru.
```

The `watch` command monitors your files and auto-indexes changes in the background:

```bash
$ memsearch watch ./memory/
Indexed 8 chunks.
Watching 1 path(s) for changes... (Ctrl+C to stop)
```

---

## Python API

The core workflow is three lines: create a `MemSearch` instance, index your files, and search.

```python
import asyncio
from memsearch import MemSearch

async def main():
    mem = MemSearch(paths=["./memory/"])

    # Index all markdown files (skips unchanged content automatically)
    await mem.index()

    # Semantic search -- returns ranked results with source attribution
    results = await mem.search("how to configure Redis?", top_k=5)
    for r in results:
        print(f"[{r['score']:.2f}] {r['source']} -- {r['content'][:80]}")

    mem.close()

asyncio.run(main())
```

See [Getting Started](getting-started.md) for a complete walkthrough including agent memory loops, API key setup, and Milvus backend options.

---

## Use Cases

### Personal Knowledge Base

Point memsearch at your notes directory and get instant semantic search across years of accumulated knowledge.

```bash
$ memsearch index ~/notes/
$ memsearch search "that article about distributed consensus"
```

### Agent Memory

Give your AI agent persistent, searchable memory. The agent writes observations to markdown files; memsearch indexes them and retrieves relevant context on the next turn. This is exactly how [OpenClaw](https://github.com/openclaw/openclaw) manages memory, and memsearch ships with a ready-made [Claude Code plugin](claude-plugin.md) that demonstrates the pattern.

```python
mem = MemSearch(paths=["./agent-memory/"])

# Agent recalls relevant past experiences before responding
memories = await mem.search(user_question, top_k=3)

# Agent saves new knowledge after responding
save_to_markdown("./agent-memory/", today, summary)
await mem.index()
```

### Team Knowledge Sharing

Deploy a shared Milvus server and point multiple team members (or agents) at it. Everyone indexes their own markdown files into the same collection, creating a shared searchable knowledge base.

```python
mem = MemSearch(
    paths=["./docs/"],
    milvus_uri="http://milvus.internal:19530",
    milvus_token="root:Milvus",
)
```

---

## Embedding Providers

memsearch supports **5 embedding providers** — from cloud APIs to fully local models with no API key required:

| Provider | Install | API Key |
|----------|---------|---------|
| OpenAI (default) | `pip install memsearch` | `OPENAI_API_KEY` |
| Google Gemini | `pip install "memsearch[google]"` | `GOOGLE_API_KEY` |
| Voyage AI | `pip install "memsearch[voyage]"` | `VOYAGE_API_KEY` |
| Ollama (local) | `pip install "memsearch[ollama]"` | none |
| sentence-transformers (local) | `pip install "memsearch[local]"` | none |

For zero-config local operation with no API keys, install `memsearch[local]` or `memsearch[ollama]`. See [Getting Started — API Keys](getting-started.md#api-keys) for details and provider comparison.

---

## Milvus Backends

Just change the URI to switch backends — no other code changes needed:

| Mode | URI | Platform |
|------|-----|----------|
| **Milvus Lite** (default) | `~/.memsearch/milvus.db` | Linux, macOS |
| **Milvus Server** | `http://localhost:19530` | All (via Docker) |
| **Zilliz Cloud** | `https://in03-xxx.zillizcloud.com` | All (managed) |

!!! warning "Windows"
    Milvus Lite does not provide Windows binaries. On Windows use Milvus Server (Docker) or Zilliz Cloud. See [FAQ — Does memsearch work on Windows?](faq.md#does-memsearch-work-on-windows)

See [Getting Started — Milvus Backends](getting-started.md#milvus-backends) for connection examples and Docker setup.

---

## License

MIT
