# Comparison with Alternatives

memsearch is both a CLI engine and a set of native plugins for four coding CLIs, so we compare it against projects along that whole spectrum, plus Claude Code's built-in memory as a baseline: [Claude Code native memory](https://docs.claude.com/en/docs/claude-code/memory), [claude-mem](https://github.com/thedotmack/claude-mem), [qmd](https://github.com/tobi/qmd), [MemPalace](https://github.com/milla-jovovich/mempalace), [mem0](https://github.com/mem0ai/mem0), [Letta / MemGPT](https://github.com/letta-ai/letta).

> Verified against each project's README / official docs. The space moves fast — [open an issue](https://github.com/zilliztech/memsearch/issues) if anything looks stale.

## At a glance

| | memsearch | Claude Code native | claude-mem | qmd | MemPalace | mem0 | Letta |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Shape** | Engine + 4 native CLI plugins | Built-in (Claude Code only) | Plugin (Claude Code / Gemini CLI / OpenClaw) | Engine + MCP + Claude Code plugin | Claude Code plugin + MCP | Library + native plugins + MCP | Agent runtime (own CLI: Letta Code) |
| **Source of truth** | Plain `.md` | Plain `.md` (`CLAUDE.md` + auto-memory) | SQLite + ChromaDB | Plain `.md` | ChromaDB | Vector DB (+ optional graph) | Postgres / git-backed MemFS (Letta Code) |
| **Write** | Append-only | User edits `CLAUDE.md`; auto-memory appended by Claude | LLM-compressed transcripts | — (read-only) | Raw transcripts | LLM-extracted facts, LLM add/update/delete | Agent self-edits via tools |
| **Search** | Dense + BM25 + RRF | **None** — whole file loaded every session | Chroma vector + FTS5 | BM25 + dense + LLM rerank | Dense | Dense (+ optional rerank, + optional graph) | Dense archival |
| **Local default** | ONNX bge-m3, no key | N/A (no search) | Chroma default | Local GGUF | Local Llama + Chroma | Needs LLM API on every write | Configurable |
| **Scale** | Milvus Lite → Server → Zilliz Cloud (same API) | Bounded by context window | Single machine | Single machine | Single machine | Pluggable vector DB | Postgres / pgvector |

## Feature matrix

| | memsearch | Claude Code native | claude-mem | qmd | MemPalace | mem0 | Letta |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Platform plugins** | | | | | | | |
| Claude Code | ✅ | ✅ built-in | ✅ | ✅ | ✅ | ✅ | ❌ |
| OpenClaw | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| OpenCode | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Codex CLI | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Cursor | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| Gemini CLI | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ |
| Generic MCP | — | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| **Storage** | | | | | | | |
| Markdown as source of truth | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ (MemFS) |
| Git-diffable memory files | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ (MemFS) |
| **Search & retrieval** | | | | | | | |
| On-demand retrieval (not full-file reload) | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Hybrid BM25 + dense | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| RRF fusion inside the vector DB | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Pluggable embedding providers | ✅ (6: openai / google / voyage / ollama / local / onnx) | — | ❌ | ✅ | ❌ | ✅ | ✅ |
| Optional cross-encoder reranker | ✅ | ❌ | ❌ | ✅ (LLM rerank) | ❌ | ✅ | ❌ |
| Progressive disclosure: search → expand → transcript | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Forked-subagent recall (isolated context) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Writes** | | | | | | | |
| No external API key by default | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Scale** | | | | | | | |
| Local → self-hosted → managed, one API | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

## Where memsearch is different

- **Covers Claude Code + OpenClaw + OpenCode + Codex CLI in one project.** No other entry covers all four.
- **Retrieves on demand** instead of stuffing the whole file into every session like Claude Code's built-in memory.
- **Markdown + Milvus, not an opaque DB.** qmd and Letta's MemFS share the markdown-canonical approach; claude-mem / MemPalace / mem0 keep state in a DB.
- **Append-only writes, no LLM curation on the write path.** mem0 and Letta's traditional memory depend on LLM write-time curation (powerful but can silently mutate past writes).
- **Hybrid dense + BM25 fused via RRF inside Milvus.** qmd and claude-mem are also hybrid; mem0 / MemPalace / Letta archival are dense-only.
- **Scale path: Lite → Server → Cloud, one API.** Others are single-machine or require wiring your own backend.
- **Context isolation via forked subagents** on Claude Code — recall runs in its own context window.

## When another project fits better

- **Only use Claude Code and memory is tiny / project-instruction-like** → built-in `CLAUDE.md` is fine.
- **Generic LLM app, not a coding CLI** → mem0.
- **Want the LLM to actively curate memory** → Letta or mem0.
- **Want a full agent runtime or MemFS** → Letta.
- **Cursor / ChatGPT / Gemini CLI users** → mem0, MemPalace, or claude-mem.
- **Just need a local markdown search engine** → qmd.

## References

- Claude Code native memory — [docs](https://docs.claude.com/en/docs/claude-code/memory)
- mem0 — [repo](https://github.com/mem0ai/mem0) · [docs](https://docs.mem0.ai/) · [paper](https://arxiv.org/html/2504.19413v1)
- Letta (MemGPT) — [repo](https://github.com/letta-ai/letta) · [docs](https://docs.letta.com/) · [Context Repositories blog](https://www.letta.com/blog/context-repositories)
- MemPalace — [repo](https://github.com/milla-jovovich/mempalace)
- claude-mem — [repo](https://github.com/thedotmack/claude-mem)
- qmd — [repo](https://github.com/tobi/qmd)
