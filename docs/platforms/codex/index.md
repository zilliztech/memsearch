# Codex CLI Plugin

**Semantic memory for [Codex CLI](https://github.com/openai/codex).** Shell hooks and a memory-recall skill, similar in architecture to the Claude Code plugin.

---

## Why memsearch for Codex?

Codex CLI is OpenAI's open-source terminal coding agent. Unlike Claude Code (which has a mature plugin marketplace) or OpenClaw (which has a built-in memory system), Codex has **no native memory plugin ecosystem**. Hooks support is experimental, and there are few third-party memory solutions available.

memsearch fills this gap with a shell-hook-based plugin that gives Codex the same persistent memory capabilities as other platforms:

- **First-class memory for Codex** -- no other solution provides hybrid semantic search with progressive disclosure
- **Same architecture as the Claude Code plugin** -- if you're familiar with one, you understand both
- **Cross-platform portability** -- memories captured in Codex are searchable from Claude Code, OpenClaw, or OpenCode
- **ONNX embedding default** -- no OpenAI API key needed for the memory system itself (Codex uses OpenAI for the agent, but memsearch's embeddings are independent)

---

## `--yolo` Mode and Sandbox

Codex CLI runs in a sandboxed environment by default. The memsearch plugin requires file system access to write memory files and run the `memsearch` CLI. The recommended approach:

- **Install option**: The `install.sh` script configures `hooks.json` which works in any mode
- **Stop hook isolation**: The Stop hook uses `codex exec --ephemeral -s read-only` with an isolated `CODEX_HOME` to prevent sandbox conflicts during summarization

If you experience issues with the Stop hook in strict sandbox mode, see [Troubleshooting](../../platforms/claude-code/troubleshooting.md) for diagnostic steps.

---

## Key Features

- **Automatic capture** -- conversations summarized via `codex exec` using `gpt-5.1-codex-mini` after each turn
- **Three-layer progressive recall** -- search, expand, and drill into original rollouts ([details](memory-recall.md))
- **Shell hook architecture** -- similar to [Claude Code plugin](../claude-code/index.md), easy to understand and modify
- **Orphan cleanup** -- handles missing `SessionEnd` hook gracefully (Codex doesn't have one)
- **Milvus Lite lock handling** -- automatically detects Milvus backend and skips concurrent index operations in Lite mode
- **ONNX embedding by default** -- no API key required, runs locally on CPU
- **Local summarization fallback** -- if `codex exec` fails, falls back to truncated raw text

---

## When Is This Useful?

- **Codex as your daily driver.** If you use Codex CLI for everyday coding, memsearch gives it memory that persists across sessions -- no more re-explaining context.
- **Codex + Claude Code workflows.** Some developers use Codex for quick tasks and Claude Code for complex ones. memsearch provides unified memory across both.
- **Long debugging sessions.** Codex sessions tend to be focused but context-heavy. memsearch captures the debugging trail so you can pick up where you left off.
- **Evaluating Codex.** If you're comparing coding agents, having consistent memory across all of them provides a fair evaluation baseline.

---

## Pages

- [Installation](installation.md) -- prerequisites, install, pre-cache, uninstall, updating
- [How It Works](how-it-works.md) -- hook architecture, capture mechanism, memory files, Milvus Lite handling
- [Memory Recall](memory-recall.md) -- three-layer progressive disclosure, comparison with Claude Code, manual invocation
