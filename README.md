<h1 align="center">
  <img src="assets/logo-icon.jpg" alt="" width="100" valign="middle">
  &nbsp;
  memsearch
</h1>

<p align="center">
  <strong><a href="https://github.com/openclaw/openclaw">OpenClaw</a>'s memory, everywhere.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/memsearch/"><img src="https://img.shields.io/pypi/v/memsearch?style=flat-square&color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/memsearch/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://github.com/zilliztech/memsearch/blob/main/LICENSE"><img src="https://img.shields.io/github/license/zilliztech/memsearch?style=flat-square" alt="License"></a>
  <a href="https://github.com/zilliztech/memsearch/stargazers"><img src="https://img.shields.io/github/stars/zilliztech/memsearch?style=flat-square" alt="Stars"></a>
  <a href="https://milvus.io/"><img src="https://img.shields.io/badge/powered%20by-Milvus-blue?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCI+PHBhdGggZD0iTTEyIDJMMyA3djEwbDkgNSA5LTVWN3oiIGZpbGw9IiMwMEE1RkYiLz48L3N2Zz4=" alt="Milvus"></a>
  <a href="https://discord.com/invite/FG6hMJStWu"><img src="https://img.shields.io/badge/Discord-Milvus-7289da?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://x.com/zilliz_universe"><img src="https://img.shields.io/badge/follow-%40zilliz__universe-000000?style=flat-square&logo=x&logoColor=white" alt="X (Twitter)"></a>
</p>

https://github.com/user-attachments/assets/31de76cc-81a8-4462-a47d-bd9c394d33e3

> 💡 **memsearch extracts [OpenClaw](https://github.com/openclaw/openclaw)'s memory system into a standalone library** — same markdown-first architecture, same chunking, same chunk ID format. Pluggable into *any* agent framework, backed by [Milvus](https://milvus.io/) (local Milvus Lite → Milvus Server → Zilliz Cloud). See it in action with the included **[Claude Code plugin](ccplugin/README.md)**.

### ✨ Why memsearch?

- 🦞 **OpenClaw's memory, everywhere** — OpenClaw has one of the best memory designs in open-source AI: **markdown as the single source of truth** — simple, human-readable, `git`-friendly, zero vendor lock-in
- ⚡ **Smart dedup** — SHA-256 content hashing means unchanged content is never re-embedded
- 🔄 **Live sync** — File watcher auto-indexes on changes, deletes stale chunks when files are removed
- 🧹 **Memory compact** — LLM-powered summarization compresses old memories, just like OpenClaw's compact cycle
- 🧩 **Claude Code plugin included** — A real-world example: **[ccplugin/](ccplugin/README.md)** gives Claude persistent memory across sessions with zero config

## 🔍 How It Works

**Markdown is the source of truth** — the vector store is just a derived index, rebuildable anytime.

```
  ┌─── Search ─────────────────────────────────────────────────────────┐
  │                                                                    │
  │  "how to configure Redis?"                                         │
  │        │                                                           │
  │        ▼                                                           │
  │   ┌──────────┐     ┌─────────────────┐     ┌──────────────────┐   │
  │   │  Embed   │────▶│ Cosine similarity│────▶│ Top-K results    │   │
  │   │  query   │     │ (Milvus)        │     │ with source info │   │
  │   └──────────┘     └─────────────────┘     └──────────────────┘   │
  │                                                                    │
  └────────────────────────────────────────────────────────────────────┘

  ┌─── Ingest ─────────────────────────────────────────────────────────┐
  │                                                                    │
  │  MEMORY.md                                                         │
  │  memory/2026-02-09.md     ┌──────────┐     ┌────────────────┐     │
  │  memory/2026-02-08.md ───▶│ Chunker  │────▶│ Dedup          │     │
  │                           │(heading, │     │(chunk_hash PK) │     │
  │                           │paragraph)│     └───────┬────────┘     │
  │                           └──────────┘             │              │
  │                                             new chunks only       │
  │                                                    ▼              │
  │                                            ┌──────────────┐       │
  │                                            │  Embed &     │       │
  │                                            │  Milvus upsert│      │
  │                                            └──────────────┘       │
  │                                                                    │
  └────────────────────────────────────────────────────────────────────┘

  ┌─── Watch ──────────────────────────────────────────────────────────┐
  │  File watcher (1500ms debounce) ──▶ auto re-index / delete stale  │
  └────────────────────────────────────────────────────────────────────┘

  ┌─── Compact ─────────────────────────────────────────────────────────┐
  │  Retrieve chunks ──▶ LLM summarize ──▶ write memory/YYYY-MM-DD.md │
  └────────────────────────────────────────────────────────────────────┘
```

🔒 The entire pipeline runs locally by default — your data never leaves your machine unless you choose a remote Milvus backend or a cloud embedding provider.

## 🧩 Claude Code Plugin

memsearch ships with a **[Claude Code plugin](ccplugin/README.md)** — a real-world example of OpenClaw's memory running outside OpenClaw. It gives Claude **automatic persistent memory** across sessions: every session is summarized to markdown, every prompt triggers a semantic search, and a background watcher keeps the index in sync. No commands to learn, no manual saving — just install and go.

```bash
# Install memsearch, then launch Claude with the plugin
pip install memsearch
claude --plugin-dir ./ccplugin
```

```
  Session start ──▶ start memsearch watch (singleton) ──▶ inject recent memories
                           │
  User prompt ──▶ memsearch search ──▶ inject relevant memories
                           │
  Claude stops ──▶ haiku summary ──▶ write .memsearch/memory/YYYY-MM-DD.md
                           │                                │
  Session end ──▶ stop watch              watch auto-indexes ◀┘
```

Under the hood: 4 shell hooks + 1 watch process, all calling the `memsearch` CLI. Memories are transparent `.md` files — human-readable, git-friendly, rebuildable. See **[ccplugin/README.md](ccplugin/README.md)** for the full architecture, hook details, progressive disclosure model, and comparison with claude-mem.

## 📦 Installation

```bash
pip install memsearch
```

### Additional embedding providers

```bash
pip install "memsearch[google]"      # Google Gemini
pip install "memsearch[voyage]"      # Voyage AI
pip install "memsearch[ollama]"      # Ollama (local)
pip install "memsearch[local]"       # sentence-transformers (local, no API key)
pip install "memsearch[all]"         # Everything
```

## 🐍 Python API — Build an Agent with Memory

The example below shows a complete agent loop with memory: save knowledge to markdown, index it, and recall it later via semantic search.

```python
import asyncio
from datetime import date
from pathlib import Path
from openai import OpenAI
from memsearch import MemSearch

MEMORY_DIR = "./memory"
llm = OpenAI()                                        # your LLM client
ms = MemSearch(paths=[MEMORY_DIR])                    # memsearch handles the rest

def save_memory(content: str):
    """Append a note to today's memory log (OpenClaw-style daily markdown)."""
    p = Path(MEMORY_DIR) / f"{date.today()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"\n{content}\n")

async def agent_chat(user_input: str) -> str:
    # 1. Recall — search past memories for relevant context
    memories = await ms.search(user_input, top_k=3)
    context = "\n".join(f"- {m['content'][:200]}" for m in memories)

    # 2. Think — call LLM with memory context
    resp = llm.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": f"You have these memories:\n{context}"},
            {"role": "user", "content": user_input},
        ],
    )
    answer = resp.choices[0].message.content

    # 3. Remember — save this exchange and index it
    save_memory(f"## {user_input}\n{answer}")
    await ms.index()

    return answer

async def main():
    # Seed some knowledge
    save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
    save_memory("## Decision\nWe chose Redis for caching over Memcached.")
    await ms.index()

    # Agent can now recall those memories
    print(await agent_chat("Who is our frontend lead?"))
    print(await agent_chat("What caching solution did we pick?"))

asyncio.run(main())
```

<details>
<summary>💜 <b>Anthropic Claude example</b> — click to expand</summary>

```bash
pip install memsearch anthropic
```

```python
import asyncio
from datetime import date
from pathlib import Path
from anthropic import Anthropic
from memsearch import MemSearch

MEMORY_DIR = "./memory"
llm = Anthropic()
ms = MemSearch(paths=[MEMORY_DIR])

def save_memory(content: str):
    p = Path(MEMORY_DIR) / f"{date.today()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"\n{content}\n")

async def agent_chat(user_input: str) -> str:
    # 1. Recall
    memories = await ms.search(user_input, top_k=3)
    context = "\n".join(f"- {m['content'][:200]}" for m in memories)

    # 2. Think — call Claude with memory context
    resp = llm.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=f"You have these memories:\n{context}",
        messages=[{"role": "user", "content": user_input}],
    )
    answer = resp.content[0].text

    # 3. Remember
    save_memory(f"## {user_input}\n{answer}")
    await ms.index()
    return answer

async def main():
    save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
    await ms.index()
    print(await agent_chat("Who is our frontend lead?"))

asyncio.run(main())
```

</details>

<details>
<summary>🦙 <b>Ollama (fully local, no API key)</b> — click to expand</summary>

```bash
pip install "memsearch[ollama]"
ollama pull nomic-embed-text          # embedding model
ollama pull llama3.2                  # chat model
```

```python
import asyncio
from datetime import date
from pathlib import Path
from ollama import chat
from memsearch import MemSearch

MEMORY_DIR = "./memory"
ms = MemSearch(paths=[MEMORY_DIR], embedding_provider="ollama")

def save_memory(content: str):
    p = Path(MEMORY_DIR) / f"{date.today()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"\n{content}\n")

async def agent_chat(user_input: str) -> str:
    # 1. Recall
    memories = await ms.search(user_input, top_k=3)
    context = "\n".join(f"- {m['content'][:200]}" for m in memories)

    # 2. Think — call Ollama locally
    resp = chat(
        model="llama3.2",
        messages=[
            {"role": "system", "content": f"You have these memories:\n{context}"},
            {"role": "user", "content": user_input},
        ],
    )
    answer = resp.message.content

    # 3. Remember
    save_memory(f"## {user_input}\n{answer}")
    await ms.index()
    return answer

async def main():
    save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
    await ms.index()
    print(await agent_chat("Who is our frontend lead?"))

asyncio.run(main())
```

</details>

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

### Compact (compress memories)

Summarize indexed chunks into a condensed memory using an LLM:

```bash
memsearch compact

# Use a specific LLM
memsearch compact --llm-provider anthropic
memsearch compact --llm-provider gemini

# Only compact chunks from a specific source
memsearch compact --source ./docs/old-notes.md
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

## ⚙️ Configuration

memsearch uses a layered configuration system.  Settings are resolved in priority order (lowest → highest):

1. **Built-in defaults**
2. **Global config** — `~/.memsearch/config.toml`
3. **Project config** — `.memsearch.toml` (in your working directory)
4. **Environment variables** — `MEMSEARCH_SECTION_FIELD` (e.g. `MEMSEARCH_MILVUS_URI`)
5. **CLI flags** — `--milvus-uri`, `--provider`, etc.

### API keys

API keys for embedding and LLM providers are read from standard environment variables:

```bash
# Embedding providers (set the one you use)
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://..."   # optional, for proxies / Azure
export GOOGLE_API_KEY="..."
export VOYAGE_API_KEY="..."

# LLM for compact/summarization (set the one you use)
export ANTHROPIC_API_KEY="..."         # for compact with Anthropic
```

## 🔌 Embedding Providers

| Provider | Install | Env Var | Default Model |
|----------|---------|---------|---------------|
| OpenAI | `memsearch` (included) | `OPENAI_API_KEY` | `text-embedding-3-small` |
| Google | `memsearch[google]` | `GOOGLE_API_KEY` | `gemini-embedding-001` |
| Voyage | `memsearch[voyage]` | `VOYAGE_API_KEY` | `voyage-3-lite` |
| Ollama | `memsearch[ollama]` | `OLLAMA_HOST` (optional) | `nomic-embed-text` |
| Local | `memsearch[local]` | — | `all-MiniLM-L6-v2` |

## 🐾 OpenClaw Compatibility

memsearch is designed to be a drop-in memory backend for projects following [OpenClaw's memory architecture](https://github.com/openclaw/openclaw):

| Feature | OpenClaw | memsearch |
|---------|----------|-----------|
| Memory layout | `MEMORY.md` + `memory/YYYY-MM-DD.md` | ✅ Same |
| Chunk ID format | `hash(source:startLine:endLine:contentHash:model)` | ✅ Same |
| Dedup strategy | Content-hash primary key | ✅ Same |
| Compact target | Append to daily markdown log | ✅ Same |
| Source of truth | Markdown files (vector DB is derived) | ✅ Same |
| File watch debounce | 1500ms | ✅ Same default |
| Vector backend | Built-in | Milvus (Lite / Server / Zilliz Cloud) |
| Embedding providers | Built-in | Pluggable (OpenAI, Google, Voyage, Ollama, local) |
| Packaging | Part of OpenClaw monorepo | Standalone `pip install` |

If you're already using OpenClaw's memory directory layout, just point memsearch at it — no migration needed.

## 📄 License

MIT
