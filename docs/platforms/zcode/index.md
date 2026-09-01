# ZCode Plugin

**Semantic memory for [ZCode](https://github.com/zilliztech/zcode).** Shell hooks and a memory-recall skill, similar in architecture to the Claude Code and Codex plugins.

---

## Why memsearch for ZCode?

ZCode is an open-source terminal coding agent with a plugin marketplace and hook system. Hooks fire on session lifecycle events, user prompt submission, and turn completion — the same model Claude Code and Codex use. memsearch leverages these hooks to give ZCode persistent memory:

- **First-class memory for ZCode** -- no other solution provides hybrid semantic search with progressive disclosure
- **Same architecture as the Claude Code and Codex plugins** -- if you're familiar with either, you understand the ZCode plugin
- **Cross-platform portability** -- memories captured in ZCode are searchable from Claude Code, Codex, DSH, OpenClaw, or OpenCode
- **ONNX embedding default** -- no API key needed for the memory system itself

---

## Key Features

- **Automatic capture** -- conversations summarized via native `claude -p` by default, with optional API provider routing
- **SQLite session parsing** -- ZCode stores conversations in a SQLite database (`~/.zcode/cli/db/db.sqlite`); the plugin reads this directly instead of parsing JSONL transcripts
- **Shell hook architecture** -- similar to [Claude Code](../claude-code/index.md) and [Codex](../codex/index.md) plugins, easy to understand and modify
- **Orphan cleanup** -- handles missing `SessionEnd` hook gracefully (ZCode doesn't have one, like Codex)
- **Milvus Lite lock handling** -- automatically detects Milvus backend and skips concurrent index operations in Lite mode
- **ONNX embedding by default** -- no API key required, runs locally on CPU
- **Local summarization fallback** -- if `claude -p` fails, falls back to truncated raw text

---

## When Is This Useful?

- **ZCode as your daily driver.** If you use ZCode for everyday coding, memsearch gives it memory that persists across sessions -- no more re-explaining context.
- **ZCode + other agent workflows.** Some developers use multiple agents. memsearch provides unified memory across all of them.
- **Long debugging sessions.** ZCode sessions tend to be context-heavy. memsearch captures the debugging trail so you can pick up where you left off.
- **Evaluating ZCode.** If you're comparing coding agents, having consistent memory across all of them provides a fair evaluation baseline.

---

## Pages

- [Installation](installation.md) -- prerequisites, install, pre-cache, uninstall, updating
- [How It Works](how-it-works.md) -- hook architecture, capture mechanism, memory files, Milvus Lite handling
- [Memory Recall](memory-recall.md) -- three-layer progressive disclosure, comparison with Claude Code, manual invocation
