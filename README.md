# 🧠 memsearch

**Give your AI agents persistent memory.** Semantic memory search for markdown knowledge bases — index your markdown files and Claude session logs, then search them using natural language.

🐾 Inspired by **[OpenClaw](https://github.com/openclaw/openclaw)** ([architecture deep-dive](https://manthanguptaa.in/posts/clawdbot_memory/)) — the open-source Claude Code memory system that gives Claude long-term recall across sessions. memsearch extracts and packages OpenClaw's battle-tested memory layer into a **standalone, reusable library** so *any* AI agent can have the same 24/7 context retention: remembering conversations, building upon previous interactions, and recalling knowledge indefinitely.

> 💡 **Think of it as "OpenClaw's memory, but for everyone."** If you've seen how OpenClaw lets Claude remember everything across sessions, memsearch gives you that same superpower — as a pip-installable package, compatible with any agent framework, and backed by [Milvus](https://milvus.io/) vector database (from local Milvus Lite to fully managed Zilliz Cloud).

### ✨ Why memsearch?

- 🐾 **OpenClaw-compatible** — Same two-layer memory architecture (`MEMORY.md` + daily `memory/YYYY-MM-DD.md` logs), same chunking strategy, same composite chunk ID format
- 🔌 **Pluggable embeddings** — OpenAI, Google, Voyage, Ollama, or fully local sentence-transformers
- 🗄️ **Flexible storage** — Milvus Lite (zero config local file) → Milvus Server → Zilliz Cloud
- ⚡ **Smart dedup** — SHA-256 content hashing means unchanged content is never re-embedded
- 🔄 **Live sync** — File watcher auto-indexes on changes, deletes stale chunks when files are removed
- 🧹 **Memory flush** — LLM-powered summarization compresses old memories, just like OpenClaw's flush cycle
- 📦 **pip install and go** — No OpenClaw fork needed, works with any agent

## 🔍 How It Works

memsearch follows the same memory philosophy as [OpenClaw](https://github.com/openclaw/openclaw) — **markdown is the source of truth**, and the vector store is a derived index that can be rebuilt at any time:

1. 📂 **Scan** — Recursively discover `.md` / `.markdown` files (same layout as OpenClaw's `MEMORY.md` + `memory/` daily logs).
2. ✂️ **Chunk** — Split each document into semantically meaningful sections by headings and paragraph boundaries.
3. 🔑 **Dedup** — Each chunk gets a composite ID (matching [OpenClaw's format](https://manthanguptaa.in/posts/clawdbot_memory/): `hash(source:startLine:endLine:contentHash:model)`) used as the Milvus primary key. Unchanged content is never re-embedded.
4. 🧮 **Embed & Store** — New chunks are converted to vector embeddings (via OpenAI, Google, Voyage, Ollama, or local models) and upserted into Milvus. Use Milvus Lite locally with zero config, or connect to a Milvus Server / Zilliz Cloud cluster for production scale.
5. 🔎 **Search** — Given a natural-language query, embed it and perform a cosine-similarity search across all stored chunks. Results come back ranked by relevance with source file, heading, and content.
6. 🧹 **Flush** — Optionally compress accumulated chunks into a condensed summary using an LLM (OpenAI / Anthropic / Gemini), then write the summary to `memory/YYYY-MM-DD.md` and re-index it — exactly like OpenClaw's memory consolidation cycle.

🔒 The entire pipeline runs locally by default — your data never leaves your machine unless you choose a remote Milvus backend or a cloud embedding provider.

## 📦 Installation

```bash
# Core + OpenAI embeddings (recommended)
pip install "memsearch[openai]"

# Or install from source
git clone https://github.com/zc277584121/memsearch.git
cd memsearch
pip install -e ".[openai]"
```

### Other embedding providers

```bash
pip install "memsearch[google]"      # Google Gemini
pip install "memsearch[voyage]"      # Voyage AI
pip install "memsearch[ollama]"      # Ollama (local)
pip install "memsearch[local]"       # sentence-transformers (local, no API key)
pip install "memsearch[all]"         # Everything
```

## ⚙️ Configuration

memsearch uses a layered configuration system.  Settings are resolved in priority order (lowest → highest):

1. **Built-in defaults**
2. **Global config** — `~/.memsearch/config.toml`
3. **Project config** — `.memsearch.toml` (in your working directory)
4. **Environment variables** — `MEMSEARCH_SECTION_FIELD` (e.g. `MEMSEARCH_MILVUS_URI`)
5. **CLI flags** — `--milvus-uri`, `--provider`, etc.

### Quick setup

```bash
# Interactive wizard — creates ~/.memsearch/config.toml
memsearch config init

# Or set individual values
memsearch config set milvus.uri http://localhost:19530
memsearch config set embedding.provider google

# View resolved config (all sources merged)
memsearch config list --resolved
```

### Config file format

```toml
# ~/.memsearch/config.toml  (or .memsearch.toml for project-level)

[milvus]
uri = "~/.memsearch/milvus.db"
token = ""
collection = "memsearch_chunks"

[embedding]
provider = "openai"
model = ""

[chunking]
max_chunk_size = 1500
overlap_lines = 2

[watch]
debounce_ms = 1500

[flush]
llm_provider = "openai"
llm_model = ""
prompt_file = ""
```

### API keys

API keys for embedding and LLM providers are read from standard environment variables:

```bash
# Embedding providers (set the one you use)
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://..."   # optional, for proxies / Azure
export GOOGLE_API_KEY="..."
export VOYAGE_API_KEY="..."

# LLM for flush/summarization (set the one you use)
export ANTHROPIC_API_KEY="..."         # for flush with Anthropic
```

Data is stored locally at `~/.memsearch/milvus.db` by default (Milvus Lite). See [Milvus Backend Configuration](#milvus-backend-configuration) for remote / cloud options.

## 🖥️ CLI Usage

### Index markdown files

```bash
# Index one or more directories / files
memsearch index ./docs/ ./notes/

# Use a different embedding provider
memsearch index ./docs/ --provider google

# Force re-index everything
memsearch index ./docs/ --force

# Use a remote Milvus server
memsearch index ./docs/ --milvus-uri http://localhost:19530 --milvus-token root:Milvus
```

### Search

```bash
memsearch search "how to configure Redis caching"

# Return more results
memsearch search "authentication flow" --top-k 10

# JSON output (for piping to other tools)
memsearch search "error handling" --json-output
```

### Watch for changes

```bash
# Auto-index on file changes (Ctrl+C to stop)
memsearch watch ./docs/ ./notes/

# Custom debounce interval
memsearch watch ./docs/ --debounce-ms 3000
```

### Flush (compress memories)

Summarize indexed chunks into a condensed memory using an LLM:

```bash
memsearch flush

# Use a specific LLM
memsearch flush --llm-provider anthropic
memsearch flush --llm-provider gemini

# Only flush chunks from a specific source
memsearch flush --source ./docs/old-notes.md
```

### Configuration management

```bash
memsearch config init               # Interactive wizard
memsearch config set milvus.uri http://localhost:19530
memsearch config get milvus.uri
memsearch config list --resolved    # Show merged config from all sources
memsearch config list --global      # Show ~/.memsearch/config.toml only
memsearch config list --project     # Show .memsearch.toml only
```

### Manage

```bash
memsearch stats    # Show index statistics
memsearch reset    # Drop all indexed data (with confirmation)
```

## 🐍 Python API

```python
import asyncio
from memsearch import MemSearch

async def main():
    with MemSearch(
        paths=["./docs/", "./notes/"],
        embedding_provider="openai",       # or "google", "voyage", "ollama", "local"
    ) as ms:
        # Index all markdown files
        n = await ms.index()
        print(f"Indexed {n} chunks")

        # Semantic search
        results = await ms.search("caching strategy", top_k=5)
        for r in results:
            print(f"[{r['score']:.3f}] {r['source']} — {r['heading']}")
            print(f"  {r['content'][:200]}")

        # Index a single file
        await ms.index_file("./docs/new-note.md")

        # Flush: compress all memories into a summary
        summary = await ms.flush(llm_provider="openai")
        print(summary)

asyncio.run(main())
```

### 🗄️ Milvus Backend Configuration

memsearch supports three Milvus deployment modes — just change `milvus_uri` and `milvus_token`:

#### 1. Milvus Lite (default — zero config, local file)

```python
ms = MemSearch(
    paths=["./docs/"],
    milvus_uri="~/.memsearch/milvus.db",    # local file, no server needed
)
```

No server to install. Data is stored in a single `.db` file. Perfect for personal use, single-agent setups, and development.

#### 2. Milvus Server (self-hosted)

```python
ms = MemSearch(
    paths=["./docs/"],
    milvus_uri="http://localhost:19530",     # your Milvus server
    milvus_token="root:Milvus",              # default credentials, change in production
)
```

Deploy via Docker (`docker compose`) or Kubernetes. Ideal for multi-agent workloads and team environments where you need a shared, always-on vector store.

#### 3. Zilliz Cloud (fully managed)

```python
ms = MemSearch(
    paths=["./docs/"],
    milvus_uri="https://in03-xxx.api.gcp-us-west1.zillizcloud.com",
    milvus_token="your-api-key",
)
```

Zero-ops, auto-scaling managed service. Get your free cluster at [cloud.zilliz.com](https://cloud.zilliz.com). Great for production deployments and when you don't want to manage infrastructure.

#### Custom local database path

```python
ms = MemSearch(
    paths=["./docs/"],
    milvus_uri="./my_project.db",           # Milvus Lite file in current directory
)
```

## 🏗️ Architecture

```
Markdown files ──► Scanner ──► Chunker ──► Milvus (check chunk_hash exists?)
                                              │
                                    new chunks only ──► Embedder ──► Milvus upsert

Query ──► Embedder ──► Milvus search ──► Results

Flush ──► Retrieve chunks ──► LLM summarize ──► Re-index summary
```

| Component | Description |
|-----------|-------------|
| **Scanner** | Recursively finds `.md` / `.markdown` files, skips hidden files |
| **Chunker** | Splits markdown by headings, large sections split at paragraph boundaries |
| **Embeddings** | Pluggable providers: OpenAI, Google, Voyage, Ollama, sentence-transformers |
| **Store** | Milvus for vector storage — Milvus Lite (local), Milvus Server, or Zilliz Cloud. Dedup by `chunk_hash` primary key — unchanged content is never re-embedded |
| **Watcher** | Watchdog-based file monitor for auto-indexing on changes |
| **Config** | Layered TOML configuration: global → project → env vars → CLI flags |
| **Flush** | Compresses chunks into summaries via LLM (OpenAI / Anthropic / Gemini) |

## 🔌 Embedding Providers

| Provider | Install | Env Var | Default Model |
|----------|---------|---------|---------------|
| OpenAI | `memsearch[openai]` | `OPENAI_API_KEY` | `text-embedding-3-small` |
| Google | `memsearch[google]` | `GOOGLE_API_KEY` | `text-embedding-004` |
| Voyage | `memsearch[voyage]` | `VOYAGE_API_KEY` | `voyage-3-lite` |
| Ollama | `memsearch[ollama]` | `OLLAMA_HOST` (optional) | `nomic-embed-text` |
| Local | `memsearch[local]` | — | `all-MiniLM-L6-v2` |

## 🐾 OpenClaw Compatibility

memsearch is designed to be a drop-in memory backend for projects following [OpenClaw's memory architecture](https://manthanguptaa.in/posts/clawdbot_memory/):

| Feature | OpenClaw | memsearch |
|---------|----------|-----------|
| Memory layout | `MEMORY.md` + `memory/YYYY-MM-DD.md` | ✅ Same |
| Chunk ID format | `hash(source:startLine:endLine:contentHash:model)` | ✅ Same |
| Dedup strategy | Content-hash primary key | ✅ Same |
| Flush target | Append to daily markdown log | ✅ Same |
| Source of truth | Markdown files (vector DB is derived) | ✅ Same |
| File watch debounce | 1500ms | ✅ Same default |
| Vector backend | Built-in | Milvus (Lite / Server / Zilliz Cloud) |
| Embedding providers | Built-in | Pluggable (OpenAI, Google, Voyage, Ollama, local) |
| Packaging | Part of OpenClaw monorepo | Standalone `pip install` |

If you're already using OpenClaw's memory directory layout, just point memsearch at it — no migration needed.

## 🛠️ Development

```bash
git clone https://github.com/zc277584121/memsearch.git
cd memsearch
uv sync --dev --extra openai
uv run pytest
```

## 📄 License

MIT
