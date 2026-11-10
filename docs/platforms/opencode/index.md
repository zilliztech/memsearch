# OpenCode Plugin

MemSearch gives OpenCode persistent memory across sessions. It captures completed turns as Markdown and retrieves them through semantic search, section expansion, and original transcript lookup. Daily journals are readable and usable by the other MemSearch integrations.

Install the plugin and start a conversation:

```bash
opencode plugin add @zilliz/memsearch-opencode
```

Completed turns are summarized and indexed automatically. In a later session, ask about a past decision or debugging problem: OpenCode can search the notes and follow their references to the original conversation. Pending capture and indexing resume after an interruption, before recall.

The plugin includes `memory_search`, `memory_get`, and `memory_transcript`, plus the Skills `memory-recall`, `memory-config`, and `memory-to-skill`. Summaries use OpenCode's native inference by default; shared settings let you choose a model or API provider and enable optional memory maintenance.

Continue with [installation](installation.md), [capture and recovery](how-it-works.md), or the [memory tools](memory-tools.md).
