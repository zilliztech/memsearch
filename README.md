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
  <a href="https://zilliztech.github.io/memsearch/"><img src="https://img.shields.io/badge/docs-memsearch-blue?style=flat-square" alt="Docs"></a>
  <a href="https://github.com/zilliztech/memsearch/stargazers"><img src="https://img.shields.io/github/stars/zilliztech/memsearch?style=flat-square" alt="Stars"></a>
  <a href="https://milvus.io/"><img src="https://img.shields.io/badge/powered%20by-Milvus-blue?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCI+PHBhdGggZD0iTTEyIDJMMyA3djEwbDkgNSA5LTVWN3oiIGZpbGw9IiMwMEE1RkYiLz48L3N2Zz4=" alt="Milvus"></a>
  <a href="https://discord.com/invite/FG6hMJStWu"><img src="https://img.shields.io/badge/Discord-Milvus-7289da?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://x.com/zilliz_universe"><img src="https://img.shields.io/badge/follow-%40zilliz__universe-000000?style=flat-square&logo=x&logoColor=white" alt="X (Twitter)"></a>
</p>

https://github.com/user-attachments/assets/31de76cc-81a8-4462-a47d-bd9c394d33e3

> 💡 **Inspired by [OpenClaw](https://github.com/openclaw/openclaw)'s memory system, memsearch brings the same markdown-first architecture to a standalone library** — same chunking, same chunk ID format. Pluggable into *any* agent framework, backed by [Milvus](https://milvus.io/) (local Milvus Lite → Milvus Server → Zilliz Cloud). See it in action with the included **[Claude Code plugin](ccplugin/README.md)**.

### ✨ Why memsearch?

- 🦞 **OpenClaw's memory, everywhere** — OpenClaw has one of the best memory designs in open-source AI: **markdown as the single source of truth** — simple, human-readable, `git`-friendly, zero vendor lock-in
- ⚡ **Smart dedup** — SHA-256 content hashing means unchanged content is never re-embedded
- 🔄 **Live sync** — File watcher auto-indexes on changes, deletes stale chunks when files are removed
- 🧹 **Memory compact** — LLM-powered summarization compresses old memories, just like OpenClaw's compact cycle
- 🧩 **[Ready-made Claude Code plugin](ccplugin/README.md)** — a drop-in example of agent memory built on memsearch

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
# 1. Install the memsearch CLI
pip install memsearch

# 2. Set your embedding API key (OpenAI is the default provider)
export OPENAI_API_KEY="sk-..."

# 3. In Claude Code, add the marketplace and install the plugin
/plugin marketplace add zilliztech/memsearch
/plugin install memsearch

# 4. Restart Claude Code for the plugin to take effect, then start chatting!
claude
```

<details>
<summary>🔧 <b>Development mode</b> — install from local clone</summary>

```bash
git clone https://github.com/zilliztech/memsearch.git
pip install memsearch
claude --plugin-dir ./memsearch/ccplugin
```

</details>

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

### 🗄️ Milvus Backend

memsearch supports three Milvus deployment modes — just change `milvus_uri`:

| Mode | `milvus_uri` | Best for |
|------|-------------|----------|
| **Milvus Lite** (default) | `~/.memsearch/milvus.db` | Personal use, dev — zero config |
| **Milvus Server** | `http://localhost:19530` | Multi-agent, team environments |
| **Zilliz Cloud** | `https://in03-xxx.api.gcp-us-west1.zillizcloud.com` | Production, fully managed |

> 📖 Code examples and setup details → [Getting Started — Milvus Backends](https://zilliztech.github.io/memsearch/getting-started/#milvus-backends)

## 🖥️ CLI Usage

```bash
memsearch index ./memory/                          # index markdown files
memsearch search "how to configure Redis caching"  # semantic search
memsearch watch ./memory/                          # auto-index on file changes
memsearch compact                                  # LLM-powered memory summarization
memsearch config init                              # interactive config wizard
memsearch stats                                    # show index statistics
```

> 📖 Full command reference with all flags and examples → [CLI Reference](https://zilliztech.github.io/memsearch/cli/)

## ⚙️ Configuration

Settings are resolved in priority order (lowest → highest):

1. **Built-in defaults** → 2. **Global** `~/.memsearch/config.toml` → 3. **Project** `.memsearch.toml` → 4. **CLI flags**

API keys for embedding/LLM providers are read from standard environment variables (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, etc.).

> 📖 Config wizard, TOML examples, and all settings → [Getting Started — Configuration](https://zilliztech.github.io/memsearch/getting-started/#configuration)

## 🔌 Embedding Providers

| Provider | Install | Default Model |
|----------|---------|---------------|
| OpenAI | `memsearch` (included) | `text-embedding-3-small` |
| Google | `memsearch[google]` | `gemini-embedding-001` |
| Voyage | `memsearch[voyage]` | `voyage-3-lite` |
| Ollama | `memsearch[ollama]` | `nomic-embed-text` |
| Local | `memsearch[local]` | `all-MiniLM-L6-v2` |

> 📖 Provider setup and env vars → [CLI Reference — Embedding Provider Reference](https://zilliztech.github.io/memsearch/cli/#embedding-provider-reference)

## 🐾 OpenClaw Compatibility

memsearch is a drop-in memory backend for projects following [OpenClaw's memory architecture](https://github.com/openclaw/openclaw) — same memory layout, chunk ID format, dedup strategy, and compact cycle. If you're already using OpenClaw's memory directory layout, just point memsearch at it — no migration needed.

> 📖 Full compatibility matrix → [Architecture — Inspired by OpenClaw](https://zilliztech.github.io/memsearch/architecture/#inspired-by-openclaw)

## 📄 License

MIT
