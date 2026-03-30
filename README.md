<h1 align="center">
  <img src="assets/logo-icon.jpg" alt="" width="100" valign="middle">
  &nbsp;
  memsearch
</h1>

<p align="center">
  <strong>Cross-platform semantic memory for AI coding agents.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/memsearch/"><img src="https://img.shields.io/pypi/v/memsearch?style=flat-square&color=blue" alt="PyPI"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/claude-code/"><img src="https://img.shields.io/badge/Claude_Code-plugin-c97539?style=flat-square&logo=claude&logoColor=white" alt="Claude Code"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/openclaw/"><img src="https://img.shields.io/badge/OpenClaw-plugin-4a9eff?style=flat-square" alt="OpenClaw"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/opencode/"><img src="https://img.shields.io/badge/OpenCode-plugin-22c55e?style=flat-square" alt="OpenCode"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/codex/"><img src="https://img.shields.io/badge/Codex_CLI-plugin-ff6b35?style=flat-square" alt="Codex CLI"></a>
  <a href="https://pypi.org/project/memsearch/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://github.com/zilliztech/memsearch/blob/main/LICENSE"><img src="https://img.shields.io/github/license/zilliztech/memsearch?style=flat-square" alt="License"></a>
  <a href="https://github.com/zilliztech/memsearch/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/zilliztech/memsearch/test.yml?branch=main&style=flat-square" alt="Tests"></a>
  <a href="https://zilliztech.github.io/memsearch/"><img src="https://img.shields.io/badge/docs-memsearch-blue?style=flat-square" alt="Docs"></a>
  <a href="https://github.com/zilliztech/memsearch/stargazers"><img src="https://img.shields.io/github/stars/zilliztech/memsearch?style=flat-square" alt="Stars"></a>
  <a href="https://discord.com/invite/FG6hMJStWu"><img src="https://img.shields.io/badge/Discord-chat-7289da?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://x.com/zilliz_universe"><img src="https://img.shields.io/badge/follow-%40zilliz__universe-000000?style=flat-square&logo=x&logoColor=white" alt="X (Twitter)"></a>
</p>

https://github.com/user-attachments/assets/31de76cc-81a8-4462-a47d-bd9c394d33e3

> Install the plugin, get persistent memory. Memories written in Claude Code are searchable from Codex, OpenCode, and OpenClaw. One memory, every agent.

### Why memsearch?

- **4 Platforms, One Memory** — memories flow across [Claude Code](plugins/claude-code/README.md), [OpenClaw](plugins/openclaw/README.md), [OpenCode](plugins/opencode/README.md), and [Codex CLI](plugins/codex/README.md). A conversation in Claude Code becomes searchable context in OpenClaw, Codex, and OpenCode — no extra setup
- **Both for Agent Users and Agent Developers** — ready-to-use plugins for end users who just want persistent memory, plus a complete CLI and Python API for agent developers building memory and harness engineering for their own agents
- **Markdown is the source of truth** — inspired by [OpenClaw](https://github.com/openclaw/openclaw). Your memories are just `.md` files — human-readable, editable, version-controllable. Milvus is a "shadow index": a derived, rebuildable cache over the real data
- **Hybrid search, smart dedup, live sync** — dense vector + BM25 sparse + RRF reranking for the best recall; SHA-256 content hashing skips unchanged content; file watcher auto-indexes changes in real time

## For Agent Users

Pick your platform, install the plugin, and you're done. Each plugin captures conversations automatically and provides semantic recall with zero configuration.

### For Claude Code Users

```bash
/plugin marketplace add zilliztech/memsearch
/plugin install memsearch
```

Shell hooks + SKILL.md with `context: fork` subagent. Most mature plugin.

> [Claude Code Plugin docs](https://zilliztech.github.io/memsearch/platforms/claude-code/) · [Troubleshooting](https://zilliztech.github.io/memsearch/platforms/claude-code-troubleshooting/)

### For OpenClaw Users

```bash
git clone https://github.com/zilliztech/memsearch.git
openclaw plugins install ./memsearch/plugins/openclaw
openclaw gateway restart
```

Three tools (`memory_search`, `memory_get`, `memory_transcript`) with per-agent isolation.

> [OpenClaw Plugin docs](https://zilliztech.github.io/memsearch/platforms/openclaw/)

<details>
<summary><b>For OpenCode Users</b></summary>

```bash
bash memsearch/plugins/opencode/install.sh
```

SQLite daemon captures conversations; three tools for semantic recall.

> [OpenCode Plugin docs](https://zilliztech.github.io/memsearch/platforms/opencode/)

</details>

<details>
<summary><b>For Codex CLI Users</b></summary>

```bash
bash memsearch/plugins/codex/scripts/install.sh
codex --yolo  # needed for ONNX model download
```

Shell hooks + SKILL.md. Requires `--yolo` mode.

> [Codex CLI Plugin docs](https://zilliztech.github.io/memsearch/platforms/codex/)

</details>

> **Note:** All plugins default to **ONNX bge-m3** embedding — no API key required, runs locally on CPU. On first launch, the model (~558 MB) is downloaded from HuggingFace Hub. Pre-download manually:
>
> ```bash
> uvx --from 'memsearch[onnx]' memsearch search --provider onnx "warmup" 2>/dev/null || true
> ```

> [Platform comparison and architecture](https://zilliztech.github.io/memsearch/platforms/)

## For Agent Developers

### Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│              For Agent Users (Plugins)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Claude   │ │ OpenClaw │ │ OpenCode │ │ Codex  │ │
│  │ Code     │ │ Plugin   │ │ Plugin   │ │ Plugin │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       └─────────────┴────────────┴───────────┘      │
├─────────────────────────┬───────────────────────────┤
│    For Agent Developers │                           │
│  ┌──────────────────────┴────────────────────────┐  │
│  │        memsearch CLI / Python API             │  │
│  │   index · search · expand · watch · compact   │  │
│  └──────────────────────┬────────────────────────┘  │
│  ┌──────────────────────┴────────────────────────┐  │
│  │        Core: Chunker → Embedder → Milvus      │  │
│  │     Hybrid Search (BM25 + Dense + RRF)        │  │
│  └───────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│  Markdown Files (Source of Truth)                   │
│  memory/2026-03-27.md · memory/2026-03-26.md · ...  │
└─────────────────────────────────────────────────────┘
```

### How Plugins Work (Claude Code as example)

**Capture — after each conversation turn:**

```
User asks question → Agent responds → Stop hook fires
                                          │
                     ┌────────────────────┘
                     ▼
              Parse last turn
                     │
                     ▼
         LLM summarizes (haiku)
         "- User asked about X."
         "- Claude did Y."
                     │
                     ▼
         Append to memory/2026-03-27.md
         with <!-- session:UUID --> anchor
                     │
                     ▼
         memsearch index → Milvus
```

**Recall — 3-layer progressive search:**

```
User: "What did we discuss about batch size?"
                     │
                     ▼
  L1  memsearch search "batch size"    → ranked chunks
                     │ (need more?)
                     ▼
  L2  memsearch expand <chunk_hash>    → full .md section
                     │ (need original?)
                     ▼
  L3  parse-transcript <session.jsonl> → raw dialogue
```

### Markdown as Source of Truth

```
  Plugins write ──→  .md files  ←── human editable
                        │
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
   memsearch index   memsearch watch   memsearch reset
   (one-time scan)   (live watcher)    + index (rebuild)
          │             │              │
          └─────────────┼──────────────┘
                        ▼
              ┌──────────────────┐
              │  Milvus (shadow) │
              │  rebuildable     │
              └──────────────────┘
```

### Installation

```bash
# pip
pip install memsearch

# or uv
uv add memsearch
```

<details>
<summary><b>Optional embedding providers</b></summary>

```bash
pip install "memsearch[onnx]"    # Local ONNX (recommended, no API key)
# or uv add "memsearch[onnx]"

# Other options: [openai], [google], [voyage], [ollama], [local], [all]
```

</details>

Each platform plugin adapts this pattern to its own hook/event system — see the [platform comparison](https://zilliztech.github.io/memsearch/platforms/) for details.

### Python API — Give Your Agent Memory

```python
from memsearch import MemSearch

mem = MemSearch(paths=["./memory"])

await mem.index()                                      # index markdown files
results = await mem.search("Redis config", top_k=3)    # semantic search
scoped = await mem.search("pricing", top_k=3, source_prefix="./memory/product")
print(results[0]["content"], results[0]["score"])       # content + similarity
```

<details>
<summary><b>Full example — agent with memory (OpenAI)</b> — click to expand</summary>

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
<summary><b>Anthropic Claude example</b> — click to expand</summary>

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
<summary><b>Ollama (fully local, no API key)</b> — click to expand</summary>

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

> Full Python API reference with all parameters: [Python API docs](https://zilliztech.github.io/memsearch/python-api/)

### CLI Usage

#### Set Up — `config init`

Interactive wizard to configure embedding provider, Milvus backend, and chunking parameters:

```bash
memsearch config init                    # write to ~/.memsearch/config.toml
memsearch config init --project          # write to .memsearch.toml (per-project)
memsearch config set milvus.uri http://localhost:19530
memsearch config list --resolved         # show merged config from all sources
```

#### Index Markdown — `index`

Scan directories and embed all markdown into the vector store. Unchanged chunks are auto-skipped via content-hash dedup:

```bash
memsearch index ./memory/
memsearch index ./memory/ ./notes/ --provider google
memsearch index ./memory/ --force        # re-embed everything
```

#### Semantic Search — `search`

Hybrid search (dense vector + BM25 full-text) with RRF reranking:

```bash
memsearch search "how to configure Redis caching"
memsearch search "auth flow" --top-k 10 --json-output
memsearch search "pricing" --source-prefix ./memory/product
```

#### Live Sync — `watch`

File watcher that auto-indexes on markdown changes (creates, edits, deletes):

```bash
memsearch watch ./memory/
memsearch watch ./memory/ ./notes/ --debounce-ms 3000
```

#### LLM Summarization — `compact`

Compress indexed chunks into a condensed markdown summary using an LLM:

```bash
memsearch compact
memsearch compact --llm-provider anthropic --source ./memory/old-notes.md
```

Relative and `~` paths are automatically resolved to the absolute form used at index time.

#### Utilities — `stats` / `reset`

```bash
memsearch stats                          # show total indexed chunk count
memsearch reset                          # drop all indexed data (with confirmation)
```

> Full command reference with all flags and examples: [CLI Reference](https://zilliztech.github.io/memsearch/cli/)

## Configuration

Settings are resolved in priority order (lowest to highest):

1. **Built-in defaults** > 2. **Global** `~/.memsearch/config.toml` > 3. **Project** `.memsearch.toml` > 4. **CLI flags**

API keys for embedding/LLM providers are read from standard environment variables (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, etc.).

> Config wizard, TOML examples, and all settings: [Getting Started — Configuration](https://zilliztech.github.io/memsearch/getting-started/#configuration)

## Embedding Providers

| Provider | Install | Default Model |
|----------|---------|---------------|
| OpenAI | `memsearch` (included) | `text-embedding-3-small` |
| ONNX | `memsearch[onnx]` | `bge-m3-onnx-int8` (CPU, no API key) |
| Google | `memsearch[google]` | `gemini-embedding-001` |
| Voyage | `memsearch[voyage]` | `voyage-3-lite` |
| Ollama | `memsearch[ollama]` | `nomic-embed-text` |
| Local | `memsearch[local]` | `all-MiniLM-L6-v2` |

> Provider setup and env vars: [CLI Reference — Embedding Provider Reference](https://zilliztech.github.io/memsearch/cli/#embedding-provider-reference)

## Milvus Backend

memsearch supports three deployment modes — just change `milvus_uri`:

| Mode | `milvus_uri` | Best for |
|------|-------------|----------|
| **Milvus Lite** (default) | `~/.memsearch/milvus.db` | Personal use, dev — zero config |
| **Milvus Server** | `http://localhost:19530` | Multi-agent, team environments |
| **Zilliz Cloud** | `https://in03-xxx.api.gcp-us-west1.zillizcloud.com` | Production, fully managed — [free tier available](https://cloud.zilliz.com/signup?utm_source=github&utm_medium=referral&utm_campaign=memsearch-readme) |

> **Recommended:** [Zilliz Cloud](https://cloud.zilliz.com/signup?utm_source=github&utm_medium=referral&utm_campaign=memsearch-readme) gives you zero-config, zero-ops Milvus with concurrent access and real-time indexing — no Docker needed. Perfect for the Claude Code plugin's `watch` mode.

<details>
<summary>Sign up for a free Zilliz Cloud cluster</summary>

You can [sign up](https://cloud.zilliz.com/signup?utm_source=github&utm_medium=referral&utm_campaign=memsearch-readme) on Zilliz Cloud to get a free cluster and API key.

![Sign up and get API key](https://raw.githubusercontent.com/zilliztech/CodeIndexer/master/assets/signup_and_get_apikey.png)

Copy your Personal Key to use as `--milvus-token` in the CLI or `milvus_token` in the Python API.

</details>

> Comparison table and setup details: [Getting Started — Which backend should I choose?](https://zilliztech.github.io/memsearch/getting-started/#which-backend-should-i-choose)

## Links

- [Documentation](https://zilliztech.github.io/memsearch/) — full guides, API reference, and architecture details
- [Platform Plugins](https://zilliztech.github.io/memsearch/platforms/) — Claude Code, OpenClaw, OpenCode, Codex CLI
- [Design Philosophy](https://zilliztech.github.io/memsearch/design-philosophy/) — why markdown, why Milvus, competitor comparison
- [OpenClaw](https://github.com/openclaw/openclaw) — the memory architecture that inspired memsearch
- [Milvus](https://milvus.io/) — the vector database powering memsearch

## Contributing

Bug reports, feature requests, and pull requests are welcome! See the [Contributing Guide](CONTRIBUTING.md) for development setup, testing, and plugin development instructions. For questions and discussions, join us on [Discord](https://discord.com/invite/FG6hMJStWu).

## License

[MIT](LICENSE)
