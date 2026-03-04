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
  <a href="https://zilliztech.github.io/memsearch/claude-plugin/"><img src="https://img.shields.io/badge/Claude_Code-plugin-c97539?style=flat-square&logo=claude&logoColor=white" alt="Claude Code Plugin"></a>
  <a href="https://pypi.org/project/memsearch/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://github.com/zilliztech/memsearch/blob/main/LICENSE"><img src="https://img.shields.io/github/license/zilliztech/memsearch?style=flat-square" alt="License"></a>
  <a href="https://github.com/zilliztech/memsearch/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/zilliztech/memsearch/test.yml?branch=main&style=flat-square" alt="Tests"></a>
  <a href="https://zilliztech.github.io/memsearch/"><img src="https://img.shields.io/badge/docs-memsearch-blue?style=flat-square" alt="Docs"></a>
  <a href="https://github.com/zilliztech/memsearch/stargazers"><img src="https://img.shields.io/github/stars/zilliztech/memsearch?style=flat-square" alt="Stars"></a>
  <a href="https://discord.com/invite/FG6hMJStWu"><img src="https://img.shields.io/badge/Discord-chat-7289da?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://x.com/zilliz_universe"><img src="https://img.shields.io/badge/follow-%40zilliz__universe-000000?style=flat-square&logo=x&logoColor=white" alt="X (Twitter)"></a>
</p>

https://github.com/user-attachments/assets/31de76cc-81a8-4462-a47d-bd9c394d33e3

> 💡 Give your AI agents persistent memory in a few lines of code. Write memories as markdown, search them semantically. Inspired by [OpenClaw](https://github.com/openclaw/openclaw)'s markdown-first memory architecture. Pluggable into any agent framework.

### ✨ Why memsearch?

- 📝 **Markdown is the source of truth** — human-readable, `git`-friendly, zero vendor lock-in. Your memories are just `.md` files
- ⚡ **Smart dedup** — SHA-256 content hashing means unchanged content is never re-embedded
- 🔄 **Live sync** — File watcher auto-indexes changes to the vector DB, deletes stale chunks when files are removed
- 🧩 **[Ready-made Claude Code plugin](ccplugin/README.md)** — a drop-in example of agent memory built on memsearch

## 📦 Installation

```bash
pip install memsearch
```

<details>
<summary><b>Optional embedding providers</b></summary>

```bash
pip install "memsearch[google]"      # Google Gemini
pip install "memsearch[voyage]"      # Voyage AI
pip install "memsearch[ollama]"      # Ollama (local)
pip install "memsearch[local]"       # sentence-transformers (local, no API key)
pip install "memsearch[all]"         # Everything
```

</details>

## 🐍 Python API — Give Your Agent Memory

```python
from memsearch import MemSearch

mem = MemSearch(paths=["./memory"])

await mem.index()                                      # index markdown files
results = await mem.search("Redis config", top_k=3)    # semantic search
print(results[0]["content"], results[0]["score"])       # content + similarity
```

<details>
<summary>🚀 <b>Full example — agent with memory (OpenAI)</b> — click to expand</summary>

```python
import asyncio
from datetime import date
from pathlib import Path
from openai import OpenAI
from memsearch import MemSearch

MEMORY_DIR = "./memory"
llm = OpenAI()                                        # your LLM client
mem = MemSearch(paths=[MEMORY_DIR])                    # memsearch handles the rest

def save_memory(content: str):
    """Append a note to today's memory log (OpenClaw-style daily markdown)."""
    p = Path(MEMORY_DIR) / f"{date.today()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"\n{content}\n")

async def agent_chat(user_input: str) -> str:
    # 1. Recall — search past memories for relevant context
    memories = await mem.search(user_input, top_k=3)
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
    await mem.index()

    return answer

async def main():
    # Seed some knowledge
    save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
    save_memory("## Decision\nWe chose Redis for caching over Memcached.")
    await mem.index()  # or mem.watch() to auto-index in the background

    # Agent can now recall those memories
    print(await agent_chat("Who is our frontend lead?"))
    print(await agent_chat("What caching solution did we pick?"))

asyncio.run(main())
```

</details>

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
mem = MemSearch(paths=[MEMORY_DIR])

def save_memory(content: str):
    p = Path(MEMORY_DIR) / f"{date.today()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"\n{content}\n")

async def agent_chat(user_input: str) -> str:
    # 1. Recall
    memories = await mem.search(user_input, top_k=3)
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
    await mem.index()
    return answer

async def main():
    save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
    await mem.index()
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
mem = MemSearch(paths=[MEMORY_DIR], embedding_provider="ollama")

def save_memory(content: str):
    p = Path(MEMORY_DIR) / f"{date.today()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"\n{content}\n")

async def agent_chat(user_input: str) -> str:
    # 1. Recall
    memories = await mem.search(user_input, top_k=3)
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
    await mem.index()
    return answer

async def main():
    save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
    await mem.index()
    print(await agent_chat("Who is our frontend lead?"))

asyncio.run(main())
```

</details>

> 📖 Full Python API reference with all parameters → [Python API docs](https://zilliztech.github.io/memsearch/python-api/)

## 🖥️ CLI Usage

### Set Up — `config init`

Interactive wizard to configure embedding provider, Milvus backend, and chunking parameters:

```bash
memsearch config init                    # write to ~/.memsearch/config.toml
memsearch config init --project          # write to .memsearch.toml (per-project)
memsearch config set milvus.uri http://localhost:19530
memsearch config list --resolved         # show merged config from all sources
```

### Index Markdown — `index`

Scan directories and embed all markdown into the vector store. Unchanged chunks are auto-skipped via content-hash dedup:

```bash
memsearch index ./memory/
memsearch index ./memory/ ./notes/ --provider google
memsearch index ./memory/ --force        # re-embed everything
```

### Semantic Search — `search`

Hybrid search (dense vector + BM25 full-text) with RRF reranking:

```bash
memsearch search "how to configure Redis caching"
memsearch search "auth flow" --top-k 10 --json-output
```

### Live Sync — `watch`

File watcher that auto-indexes on markdown changes (creates, edits, deletes):

```bash
memsearch watch ./memory/
memsearch watch ./memory/ ./notes/ --debounce-ms 3000
```

### LLM Summarization — `compact`

Compress indexed chunks into a condensed markdown summary using an LLM:

```bash
memsearch compact
memsearch compact --llm-provider anthropic --source ./memory/old-notes.md
```

### Utilities — `stats` / `reset`

```bash
memsearch stats                          # show total indexed chunk count
memsearch reset                          # drop all indexed data (with confirmation)
```

> 📖 Full command reference with all flags and examples → [CLI Reference](https://zilliztech.github.io/memsearch/cli/)

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

🔒 The entire pipeline runs locally by default — your data never leaves your machine unless you choose a remote backend or a cloud embedding provider.

## 🧩 Claude Code Plugin

memsearch ships with a **[Claude Code plugin](ccplugin/README.md)** — a real-world example of agent memory in action. It gives Claude **automatic persistent memory** across sessions: every session is summarized to markdown, every prompt triggers a semantic search, and a background watcher keeps the index in sync. No commands to learn, no manual saving — just install and go.

```bash
# 1. Set your embedding API key (OpenAI is the default provider)
export OPENAI_API_KEY="sk-..."

# 2. In Claude Code, add the marketplace and install the plugin
/plugin marketplace add zilliztech/memsearch
/plugin install memsearch

# 3. Restart Claude Code for the plugin to take effect, then start chatting!
claude
```

> 📖 Architecture, hook details, and development mode → [Claude Code Plugin docs](https://zilliztech.github.io/memsearch/claude-plugin/)

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

## 🗄️ Milvus Backend

memsearch supports three deployment modes — just change `milvus_uri`:

| Mode | `milvus_uri` | Best for |
|------|-------------|----------|
| **Milvus Lite** (default) | `~/.memsearch/milvus.db` | Personal use, dev — zero config ⚠️ *not available on Windows* |
| **Milvus Server** | `http://localhost:19530` | Multi-agent, team environments |
| **Zilliz Cloud** | `https://in03-xxx.api.gcp-us-west1.zillizcloud.com` | Production, fully managed |

> 📖 Code examples and setup details → [Getting Started — Milvus Backends](https://zilliztech.github.io/memsearch/getting-started/#milvus-backends)

## 🔗 Integrations

memsearch works with any Python agent framework. Ready-made examples for:

- **[LangChain](https://www.langchain.com/)** — use as a `BaseRetriever` in any LCEL chain
- **[LangGraph](https://langchain-ai.github.io/langgraph/)** — wrap as a tool in a ReAct agent
- **[LlamaIndex](https://www.llamaindex.ai/)** — plug in as a custom retriever
- **[CrewAI](https://www.crewai.com/)** — add as a tool for crew agents

> 📖 Copy-paste code for each framework → [Integrations docs](https://zilliztech.github.io/memsearch/integrations/)

## 📚 Links

- [Documentation](https://zilliztech.github.io/memsearch/) — full guides, API reference, and architecture details
- [Claude Code Plugin](ccplugin/README.md) — hook details, progressive disclosure, comparison with claude-mem
- [OpenClaw](https://github.com/openclaw/openclaw) — the memory architecture that inspired memsearch
- [Milvus](https://milvus.io/) — the vector database powering memsearch
- [FAQ](https://zilliztech.github.io/memsearch/faq/) — common questions and troubleshooting

## Contributing

Bug reports, feature requests, and pull requests are welcome! See the [Contributing Guide](CONTRIBUTING.md) for development setup, testing, and plugin development instructions. For questions and discussions, join us on [Discord](https://discord.com/invite/FG6hMJStWu).

## 📄 License

[MIT](LICENSE)
