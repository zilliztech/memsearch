# DeepSeek Harness Plugin

**Persistent semantic memory for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH).** The native DSH plugin captures completed turns, recalls relevant work before the agent starts reasoning, and keeps the same markdown memory available to every other MemSearch platform plugin.

---

## Why MemSearch for DSH?

DSH can host long-running web, TUI, and headless agent sessions across multiple projects. MemSearch adds a durable memory layer that follows each project instead of disappearing with the current conversation:

- **Automatic capture** -- completed turns are summarized and appended to `.memsearch/memory/YYYY-MM-DD.md`
- **Selective recall** -- relevant memories are injected before the first model step; unrelated turns add no context
- **Native skill integration** -- DSH registers the `memory-recall` skill for search, expansion, and transcript drill-down
- **Cross-agent continuity** -- memories are shared with Claude Code, Codex CLI, OpenClaw, and OpenCode when they use the same project
- **Web memory dock** -- the web profile provides a compact skill-candidate review panel and a read-only `.memsearch` browser
- **Background maintenance** -- optional tasks keep `PROJECT.md`, `USER.md`, and reusable skill candidates current

## Quick Start

```bash
# Install the MemSearch CLI and local ONNX embedding model support
uv tool install "memsearch[onnx]"

# Attach the plugin to a DSH profile
dsh plugin --profile web add @zilliz/memsearch-dsh
```

Replace `web` with the DSH profile you use, then restart that profile or start a new session. Continue chatting normally; there is no save command to remember.

After a completed turn, confirm that the daily memory journal exists:

```bash
ls .memsearch/memory/
```

To recall previous work, ask naturally or name the registered skill:

```text
Use memory-recall to find what we decided about the deployment architecture.
```

[:octicons-arrow-right-24: Installation](installation.md){ .md-button .md-button--primary }
[:octicons-arrow-right-24: How It Works](how-it-works.md){ .md-button }

## What Happens Automatically

| Event | MemSearch behavior |
|-------|--------------------|
| **A turn completes** | Summarizes the user, assistant, and tool activity into the project's daily markdown journal |
| **A new turn begins** | Searches the project memory and injects only relevant results before the first model step |
| **The agent needs exact history** | Uses `memory-recall` to search, expand a section, and inspect the original DSH transcript |
| **A DSH session closes** | Runs enabled maintenance tasks when their configured interval is due |
| **You open the web dock** | Lists skill candidates and previews supported `.memsearch` files without modifying them |

## Memory Stays Portable

The markdown files are the source of truth; Milvus is a rebuildable search index. A project that moves between supported agents keeps the same memory history:

```text
Claude Code ─┐
Codex CLI ───┤
DSH ─────────┼──> .memsearch/memory/*.md ──> Milvus hybrid search
OpenClaw ────┤
OpenCode ────┘
```

No export step or proprietary memory format is required.

## Next Steps

- [Installation](installation.md) -- profiles, verification, configuration, updating, and uninstalling
- [How It Works](how-it-works.md) -- capture, injection, recall, summarization, maintenance, and the web dock
- [Platform Comparison](../index.md) -- compare DSH with the other supported plugins
- [Configuration](../../home/configuration.md) -- embedding providers, Milvus, and shared MemSearch settings
