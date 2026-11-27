# MemSearch for Antigravity

Persistent project memory for Antigravity: automatic Markdown capture, native
Hydrogen Low summaries, progressive recall, and optional background maintenance.

## Install

Install [Antigravity CLI](https://antigravity.google/docs/getting-started/), sign in,
and install the Python core and plugin from the same checkout:

```bash
git clone https://github.com/zilliztech/memsearch.git
cd memsearch
uv tool install --force ".[onnx]"
agy plugin install ./plugins/antigravity
```

Start a new conversation in your project. After a completed turn, check
`.memsearch/memory/` for a short summary. In a new conversation, ask about the
earlier decision or invoke `/memory-recall`.

The plugin defaults to local ONNX embeddings and `gemini-4-hydrogen-low` summaries
through your existing Antigravity login. Existing embedding, Milvus, and named
provider settings keep their normal precedence. `memory-config` explains and
configures these settings.

## Recall and maintain memory

Recall progresses from search results to full Markdown sections and then to
the original conversation. All agents using the same project and MemSearch
backend can share the notes.

Optional `project_review`, `user_profile`, and `memory_to_skill` tasks use the
shared MemSearch maintenance system. Enable them with `memory-config` or
`memsearch config set plugins.antigravity.<task>.enabled true`. Use
`memory-to-skill` to review candidates before installing them into
`.agents/skills/`.

[Installation and configuration](../../docs/platforms/antigravity/installation.md)
· [Architecture](../../docs/platforms/antigravity/how-it-works.md)
