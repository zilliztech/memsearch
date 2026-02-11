# memsearch

**OpenClaw's memory, everywhere.**

> memsearch extracts [OpenClaw](https://github.com/openclaw/openclaw)'s memory system into a standalone library -- same markdown-first architecture, same chunking, same chunk ID format. Pluggable into *any* agent framework, backed by [Milvus](https://milvus.io/).

---

## Why memsearch?

```bash
$ cat /dev/philosophy
Markdown is the source of truth.
Simple. Readable. Git-friendly. Zero vendor lock-in.
The vector store is just a derived index — rebuildable anytime.
```

- **OpenClaw's memory, everywhere** -- markdown as the single source of truth
- **Smart dedup** -- SHA-256 content hashing means unchanged content is never re-embedded
- **Live sync** -- file watcher auto-indexes on changes, deletes stale chunks
- **Memory flush** -- LLM-powered summarization compresses old memories
- **Claude Code plugin included** -- persistent memory across sessions with zero config

---

## What is memsearch?

Most memory systems treat the vector database as the source of truth. memsearch flips this around: **your markdown files are the source of truth**, and the vector store is just a derived index -- like a database index that can be dropped and rebuilt at any time.

This means:

- **Your data is always human-readable** -- plain `.md` files you can open, edit, grep, and `git diff`
- **No vendor lock-in** -- switch embedding providers or vector backends without losing anything
- **Rebuild on demand** -- corrupted index? Just re-run `memsearch index` and you are back in seconds
- **Git-native** -- version your knowledge base with standard git workflows

memsearch scans your markdown directories, splits content into semantically meaningful chunks (by heading structure and paragraph boundaries), embeds them, and stores the vectors in Milvus. When you search, it finds the most relevant chunks by cosine similarity and returns them with full source attribution.

---

## Quick Install

```bash
$ pip install memsearch
```

Index a directory of markdown files and search it:

```bash
$ memsearch index ./memory/
Indexed 38 chunks.

$ memsearch search "how to configure Redis?"

--- Result 1 (score: 0.9215) ---
Source: memory/2026-02-08.md
Heading: Infrastructure Decisions
We chose Redis for caching over Memcached. Config: host=localhost,
port=6379, max_memory=256mb, eviction=allkeys-lru.

--- Result 2 (score: 0.8734) ---
Source: memory/2026-02-07.md
Heading: Redis Setup Notes
Redis config for production: enable AOF persistence, set maxmemory-policy
to volatile-lfu, bind to 127.0.0.1 only...

$ memsearch watch ./memory/
Watching 1 path(s) for changes... (Ctrl+C to stop)
Indexed 2 chunks from memory/2026-02-09.md
```

The `watch` command monitors your files and auto-indexes changes in the background -- ideal for use alongside editors or agent processes that write to your knowledge base.

---

## Python API

The core workflow is three lines: create a `MemSearch` instance, index your files, and search.

```python
import asyncio
from memsearch import MemSearch

async def main():
    ms = MemSearch(paths=["./memory/"])

    # Index all markdown files (skips unchanged content automatically)
    await ms.index()

    # Semantic search -- returns ranked results with source attribution
    results = await ms.search("how to configure Redis?", top_k=5)
    for r in results:
        print(f"[{r['score']:.2f}] {r['source']} -- {r['content'][:80]}")

    ms.close()

asyncio.run(main())
```

See [Getting Started](getting-started.md) for a complete walkthrough with agent memory loops.

---

## Use Cases

### Personal Knowledge Base

Point memsearch at your notes directory and get instant semantic search across years of accumulated knowledge. Works with any markdown-based note-taking setup -- Obsidian vaults, Logseq graphs, or plain files.

```bash
$ memsearch index ~/notes/
$ memsearch search "that article about distributed consensus"
```

### Agent Memory

Give your AI agent persistent, searchable memory. The agent writes observations to markdown files; memsearch indexes them and retrieves relevant context on the next turn. This is exactly how [OpenClaw](https://github.com/openclaw/openclaw) manages memory, and memsearch ships with a ready-made [Claude Code plugin](claude-plugin.md) that demonstrates the pattern.

```python
ms = MemSearch(paths=["./agent-memory/"])

# Agent recalls relevant past experiences before responding
memories = await ms.search(user_question, top_k=3)

# Agent saves new knowledge after responding
save_to_markdown("./agent-memory/", today, summary)
await ms.index()
```

### Team Knowledge Sharing

Deploy a shared Milvus server and point multiple team members (or agents) at it. Everyone indexes their own markdown files into the same collection, creating a shared searchable knowledge base.

```python
ms = MemSearch(
    paths=["./docs/"],
    milvus_uri="http://milvus.internal:19530",
    milvus_token="root:Milvus",
)
```

---

## Embedding Providers

| Provider | Install | Env Var | Default Model |
|----------|---------|---------|---------------|
| OpenAI | `memsearch` (included) | `OPENAI_API_KEY` | `text-embedding-3-small` |
| Google | `memsearch[google]` | `GOOGLE_API_KEY` | `text-embedding-004` |
| Voyage | `memsearch[voyage]` | `VOYAGE_API_KEY` | `voyage-3-lite` |
| Ollama | `memsearch[ollama]` | `OLLAMA_HOST` (optional) | `nomic-embed-text` |
| Local | `memsearch[local]` | -- | `all-MiniLM-L6-v2` |

For fully local operation with no API keys, install `memsearch[ollama]` or `memsearch[local]`.

---

## Milvus Backend

memsearch supports three deployment modes -- just change the URI:

| Mode | URI | Use Case |
|------|-----|----------|
| **Milvus Lite** (default) | `~/.memsearch/milvus.db` | Local file, zero config, single user |
| **Milvus Server** | `http://localhost:19530` | Self-hosted, multi-agent, team use |
| **Zilliz Cloud** | `https://in03-xxx.zillizcloud.com` | Fully managed, auto-scaling |

---

## License

MIT
