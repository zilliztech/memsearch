# Comparison with Alternatives

This page compares **memsearch** with other open-source memory solutions for LLMs and AI agents. memsearch sits on both sides of the stack at once — it is a Python library / CLI engine *and* a set of native plugins for four coding CLIs — so below we compare it against projects that sit anywhere along that spectrum: [claude-mem](https://github.com/thedotmack/claude-mem), [qmd](https://github.com/tobi/qmd), [MemPalace](https://github.com/milla-jovovich/mempalace), [mem0](https://github.com/mem0ai/mem0), and [Letta / MemGPT](https://github.com/letta-ai/letta).

---

## TL;DR

| | memsearch | claude-mem | qmd | MemPalace | mem0 | Letta (MemGPT) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Shape** | CLI engine + native plugins for 4 coding CLIs | Claude Code–only plugin | CLI engine + MCP server + Claude Code skill | MCP server | Memory library / SDK / hosted service | Stateful-agent framework and runtime |
| **Integration** | Native hooks + skills (Claude Code, OpenClaw, OpenCode, Codex CLI) | Native hooks (Claude Code) | MCP (stdio/HTTP) + Claude Code skill | MCP | Python / JS SDK, REST, OpenMemory MCP | Build agent on Letta runtime |
| **Source of truth** | Plain `.md` files | SQLite + ChromaDB | Plain `.md` files | ChromaDB | Vector DB (+ optional graph DB) | Postgres (memory blocks + archival) |
| **Write strategy** | Append-only daily logs | LLM-summarized transcripts | External (read-only search engine) | Store-everything raw | LLM extracts facts, LLM decides add/update/delete | LLM self-edits memory (`memory_replace`, `memory_insert`, …) |
| **Search** | Hybrid: dense + BM25 + RRF | Dense + FTS5 | Hybrid: BM25 + dense + local LLM rerank (GGUF) | Dense (ChromaDB) | Dense (+ optional graph traversal) | Dense archival + conversation search |
| **Local-first default** | ONNX bge-m3 (no API key) | WASM MiniLM | Local GGUF (embedding + reranker) | Local ChromaDB + Llama | Requires LLM API for every write | Depends on configured backend |
| **Scale path** | Milvus Lite → Server → Zilliz Cloud (same API) | Single machine | Single machine | Single machine | Depends on chosen vector DB | Postgres / pgvector |

---

## Quick orientation

### memsearch

Both a search engine and a set of native plugins. The core is a Python library + `memsearch` CLI that indexes markdown into Milvus with hybrid search. On top of that, memsearch ships first-class plugins for Claude Code, OpenClaw, OpenCode, and Codex CLI — each plugin hooks into the host CLI's lifecycle (session start / prompt submit / stop / session end) to auto-capture memory and inject cold-start context. Markdown daily logs are the canonical store; Milvus is a derived index that can be rebuilt any time.

### claude-mem

Memory for Claude Code only. Hooks compress session transcripts using an LLM and store the result in ChromaDB + SQLite. Storage is opaque (binary DB), Claude Code–specific.

### qmd

A local-first search engine for markdown notes. Ships as a CLI + MCP server (stdio or HTTP) and a Claude Code skill wrapper. Uses BM25 + dense + an LLM reranker, all running locally via `node-llama-cpp` with GGUF models. It is a **search engine**, not a memory writer — you (or another tool) are responsible for producing the markdown it indexes.

### MemPalace

A memory server organized around the *method of loci* ("wings → halls → rooms"). Stores conversations raw in ChromaDB without LLM extraction, then exposes them to chat clients (Claude Code, ChatGPT, Cursor) via MCP. Runs fully offline with local Llama + ChromaDB.

### mem0

A general-purpose memory layer for LLM applications, not tied to any specific coding CLI. Every write goes through an LLM that extracts entities and relationships, decides whether to add / update / delete existing memories, and stores the results in a configurable vector DB — optionally mirrored to a graph DB (Neo4j, Memgraph, Neptune, Kuzu, AGE). Published as a Python / JS SDK, REST API, hosted platform, and (via OpenMemory) an MCP server.

### Letta (formerly MemGPT)

A full **agent framework and server** built around the "LLM as an operating system" idea. Memory is hierarchical — a small in-context *core memory*, plus *archival memory* and *recall memory* stored in Postgres — and the agent itself edits its own memory at runtime through dedicated tools (`memory_replace`, `memory_insert`, `archival_memory_insert`, `conversation_search`, …). Letta is not a plugin you bolt onto an existing CLI; you build your agent on the Letta runtime.

---

## Detailed feature matrix

### Integration surface

| | memsearch | claude-mem | qmd | MemPalace | mem0 | Letta |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Claude Code native plugin | ✅ (hooks + skills) | ✅ (hooks) | ✅ (skill wrapper over MCP) | ❌ (MCP only) | ❌ (MCP only) | ❌ (runtime, not plugin) |
| OpenClaw native plugin | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| OpenCode native plugin | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Codex CLI native plugin | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Generic MCP | Not shipped | ❌ | ✅ (stdio / HTTP) | ✅ | ✅ (OpenMemory) | ❌ |
| Library / SDK | Python | — | Node.js CLI | Python | Python, JS | Python |

"Native plugin" here means participating in a CLI's own lifecycle events (SessionStart, UserPromptSubmit, Stop, SessionEnd, …) with collection naming, per-project isolation, and skill registration. Generic MCP integrations only expose tools to the LLM — they cannot write daily memory notes at the end of a session, or inject cold-start context at session start.

### Memory write semantics

| | memsearch | claude-mem | qmd | MemPalace | mem0 | Letta |
|---|---|---|---|---|---|---|
| Who decides what to store? | Session-end hook summarizes the last turn as third-person notes | LLM-compressed session transcript written by hooks | Nobody — qmd is a read-only search engine over markdown you already have | Nobody — raw transcript stored as-is | LLM extracts "salient facts" on every write | The agent itself, via tool calls during the reasoning loop |
| Updates to prior memories? | Append-only (never mutates history) | Each session appends a new compressed record | N/A (no write path) | Append-only | LLM may update or delete prior memories during the update phase | Agent can rewrite core memory blocks at any time |
| LLM cost per write | One small Haiku call per turn (async, non-blocking) | LLM compression at session end | None | None | LLM extraction call(s) per write | Depends on the agent loop — each self-edit is an LLM tool call |
| Auditability | `git log` on `memory/YYYY-MM-DD.md` | Inspect SQLite + ChromaDB | `git log` on your markdown (whatever produced it) | Inspect ChromaDB | Inspect rows in the vector/graph DB | Inspect Postgres tables |

**Append-only vs. self-editing** is the key philosophical split. memsearch treats memory like a commit log: once written, always auditable. mem0 and Letta treat memory like a mutable KV store that the LLM maintains — which can converge on cleaner facts, but also means prior writes can be silently rewritten or deleted by a later LLM call.

### Search & retrieval

| | memsearch | claude-mem | qmd | MemPalace | mem0 | Letta |
|---|---|---|---|---|---|---|
| Dense vectors | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (archival) |
| BM25 / sparse | ✅ (RRF fused with dense) | ❌ (FTS5 only) | ✅ (BM25 + dense) | ❌ | ❌ by default | ❌ |
| Reranking | Optional cross-encoder (ONNX) | ❌ | ✅ (local LLM reranker, GGUF) | ❌ | ❌ | ❌ |
| Graph traversal | ❌ | ❌ | ❌ | ❌ | ✅ (optional graph backend) | ❌ |
| Progressive disclosure | L1 search → L2 expand section → L3 drill into original transcript JSONL | Single top-K retrieval | Single top-K retrieval | Four-layer context loading (L0–L3) | Single top-K retrieval | Core memory always in context; archival pulled on-demand |

---

## Where memsearch is actually different

We try to keep this list honest — only things that are real consequences of the current architecture, not marketing claims.

### 1. Native plugins for four coding CLIs, not just an MCP adapter

memsearch ships first-class plugins for Claude Code, OpenClaw, OpenCode, and Codex CLI. Each plugin hooks into that CLI's lifecycle (session start / prompt submit / stop / session end) to capture memory automatically and inject cold-start context. claude-mem integrates at this level but only for Claude Code; qmd has a Claude Code skill wrapper but no plugin for the other three CLIs. mem0, MemPalace, and Letta expose memory only over MCP or a REST / framework API — no CLI-lifecycle integration at all.

### 2. Plain markdown is the canonical store; the vector DB is derived

Your memory lives in `memory/YYYY-MM-DD.md` and `MEMORY.md`. You can `cat`, `grep`, `git diff`, and `git blame` it. If you lose the Milvus index, you rebuild it from the markdown. qmd shares this markdown-as-source-of-truth property (it indexes whatever markdown you give it). claude-mem, MemPalace, mem0, and Letta all keep their canonical state in a database (SQLite + ChromaDB / ChromaDB / vector DB / Postgres).

### 3. Writes are cheap and append-only

A memsearch write is: extract the last turn → one Haiku summarization call → append a bullet to today's `.md`. No LLM "decides what to forget." No self-editing. No entity extraction pipeline. This makes writes cheap, predictable, and fully auditable — at the cost of not auto-compressing redundant memories (you can run `memsearch compact` on demand if you want that).

mem0 and Letta are on the other end of the spectrum: they rely on LLMs to curate memory on the write path, which is more powerful but introduces cost, latency, and the possibility of silent data loss. qmd sidesteps the question entirely by not writing at all.

### 4. Hybrid search with BM25 fused via RRF, out of the box

memsearch indexes every chunk with both a dense vector and a BM25 sparse vector, and fuses them at query time with Reciprocal Rank Fusion. Exact keyword hits (function names, file paths, error strings) and semantic matches both surface. qmd also does hybrid search (BM25 + dense) and adds a local LLM reranker; claude-mem uses FTS5 only; mem0, MemPalace, and Letta archival are dense-only by default.

### 5. A clear scale path on one API

Milvus Lite (a single local file, zero deps) → Milvus Server (self-hosted Docker/K8s) → Zilliz Cloud (fully managed). Same Python API, same collection format, you just change a URI. MemPalace is ChromaDB-only; claude-mem is ChromaDB + SQLite; Letta is Postgres + pgvector; mem0 is pluggable but you wire the backend yourself.

### 6. Context isolation via forked subagents

On Claude Code, memory recall runs inside a skill with `context: fork` — the subagent does search, expansion, and transcript drill-down in its own context window, and only returns a curated summary to the main conversation. Retrieval never pollutes the main context with raw search hits.

---

## When another project is the better fit

A few cases where memsearch is *not* what you want:

- **You are building a general-purpose LLM application, not wiring memory into a coding CLI.** mem0 is designed for this — its SDK, hosted service, and graph-memory features assume you control the whole application.
- **You want the LLM to actively maintain memory (summarize, deduplicate, forget).** Letta's self-editing memory and mem0's LLM-driven extraction/update do this by design. memsearch deliberately does not.
- **You want a pre-built stateful-agent runtime (personas, tool loops, long-running agents).** Letta is a full agent framework; memsearch is only the memory layer.
- **You only use Cursor or ChatGPT Desktop via MCP and don't need per-CLI hooks.** MemPalace's MCP-first model fits cleanly there, and its "store everything raw" philosophy is close to memsearch's append-only writes.

---

## References

- mem0 — [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0), [docs.mem0.ai/graph-memory](https://docs.mem0.ai/open-source/features/graph-memory), paper: [arxiv.org/abs/2504.19413](https://arxiv.org/html/2504.19413v1)
- Letta (MemGPT) — [github.com/letta-ai/letta](https://github.com/letta-ai/letta), [docs.letta.com/concepts/memgpt](https://docs.letta.com/concepts/memgpt/)
- MemPalace — [github.com/milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)
- claude-mem — [github.com/thedotmack/claude-mem](https://github.com/thedotmack/claude-mem)
- qmd — [github.com/tobi/qmd](https://github.com/tobi/qmd)
