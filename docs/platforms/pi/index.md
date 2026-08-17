# pi Plugin

**Semantic memory for [pi](https://github.com/earendil-works/pi).** A TypeScript extension that captures each settled turn to markdown and provides three-layer memory recall through registered tools.

---

## Why memsearch for pi?

pi sessions are self-contained: each one starts without knowledge of the last. memsearch adds a persistent layer underneath, and because every memsearch plugin agrees on two conventions -- the collection name derived from the project path, and journals stored in `.memsearch/memory/` -- that layer is shared rather than per-agent.

| Aspect | What you get |
|--------|--------------|
| **Vector backend** | [Milvus](https://milvus.io/) -- hybrid search (dense + BM25 + RRF) |
| **Storage format** | Plain `.md` files, human-readable and git-friendly |
| **Cross-platform** | The same memories are readable from Claude Code, Codex, OpenCode, and OpenClaw |
| **Capture method** | `agent_settled` hook, using pi's own session state |
| **Progressive disclosure** | Three layers: search, expand, transcript |
| **Embedding model** | Pluggable: ONNX bge-m3 (default), OpenAI, Google, Voyage, Jina, Mistral, Ollama |

### The cross-platform advantage

If you use more than one coding agent, memsearch gives you a single memory layer instead of several disconnected ones. A decision recorded while working in Claude Code is searchable from pi the same day, because both write the same markdown into the same directory and index it into the same collection.

---

## Key features

- **Capture on `agent_settled`** -- fires only once pi has finished retrying, compacting, and draining queued messages, so a turn is never recorded twice
- **Tree-aware transcripts** -- pi sessions branch via `/fork` and `/clone`; drill-down resolves a single root-to-leaf path so abandoned branches never interleave
- **Three-layer progressive recall** -- search, expand, and drill into the original conversation ([details](memory-tools.md))
- **Automatic summarization** -- each turn is summarized by pi itself in print mode, with optional routing to a memsearch-managed provider
- **Cold-start context** -- recent journal entries injected into the system prompt via `before_agent_start`
- **Opt-in background maintenance** -- PROJECT.md, USER.md, and skill distillation through the shared maintenance runner ([details](how-it-works.md#background-maintenance))
- **ONNX embedding by default** -- no API key, runs locally on CPU

---

## When is this useful?

- **Picking up unfinished work.** You debugged an auth issue yesterday but did not finish. Today pi recalls the root cause, the files touched, and what was already ruled out.
- **Recalling past decisions.** "Why did we switch from JWT to session cookies?" leads back to the conversation where the trade-off was argued.
- **Cross-agent workflows.** You use pi for some tasks and another agent for others; memory follows you between them.
- **Long-running projects.** Architectural context accumulates over weeks without anyone maintaining a changelog.

---

## Platform notes

!!! warning "POSIX shell required"
    The plugin shells out to `bash` and `python3` for collection derivation and transcript parsing. On Windows, run pi inside [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) or another POSIX-compatible environment.

!!! note "Install at user scope"
    pi loads project-scoped resources only after the project is trusted, so a `pi install -l` install stays inert until you trust the project in an interactive session. Prefer a user-scope install unless you specifically want per-project packages.

## Pages

- [Installation](installation.md) -- prerequisites, install, verification, scope notes
- [How It Works](how-it-works.md) -- hooks, capture pipeline, memory files, architecture
- [Memory Tools](memory-tools.md) -- the three registered tools and progressive recall
