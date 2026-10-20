# OpenCode Plugin

MemSearch captures completed OpenCode V2 turns as Markdown and retrieves them through semantic search, section expansion, and original transcript lookup. Daily journals remain readable and usable by the other MemSearch integrations.

**Plugin 0.4.0 supports OpenCode V2 `>=2.0.32 <3`.** Standalone TUI capture/recall/recovery has been validated on official CLI **2.0.32 and 2.1.0**. Development types remain pinned to SDK 2.0.32. **V1 users pin `@zilliz/memsearch-opencode@0.3.17`.**

Completion events trigger a finite capture helper immediately. SQLite sequence cursors and durable pending appends support recovery after interruption. Recall waits for recovery, then uses the project's configured collection. A short host shutdown may leave work pending; it is recovered on the next activation before recall.

The plugin registers `memory_search`, `memory_get`, `memory_transcript`, and the three Skills `memory-recall`, `memory-config`, `memory-to-skill`. Native summaries use independent host inference; existing named API-provider overrides, shared prompts and optional maintenance remain available.

Continue with [installation](installation.md), [capture and recovery](how-it-works.md), or the [memory tools](memory-tools.md).
