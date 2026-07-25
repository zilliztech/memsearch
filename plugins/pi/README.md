# memsearch — pi Plugin

[![GitHub stars](https://img.shields.io/github/stars/zilliztech/memsearch?style=social)](https://github.com/zilliztech/memsearch)

**Automatic persistent memory for [pi](https://github.com/earendil-works/pi).** No commands to learn, no manual saving — install the plugin and pi remembers what you worked on across sessions.

Memories are shared with the [Claude Code](../claude-code/README.md), [Codex CLI](../codex/README.md), [OpenCode](../opencode/README.md), and [OpenClaw](../openclaw/README.md) plugins: the collection name is derived from the project path by the same script, and journals live in the same `.memsearch/memory/` directory. A conversation in any one agent is searchable from all the others, with no extra setup.

## Quick Start

```bash
# 1. Install the plugin (user scope — see the note below)
pi install git:github.com/zilliztech/memsearch#plugins/pi

# 2. Have a conversation, then check what was remembered
cat .memsearch/memory/$(date +%Y-%m-%d).md

# 3. Start a new session — pi recalls the earlier work
```

The plugin defaults to the **ONNX bge-m3** embedding model: no API key, no GPU, runs locally on CPU. If memsearch is not installed, the plugin falls back to `uvx --from 'memsearch[onnx]' memsearch` on first use.

> **Install at user scope.** `pi install -l` writes to project settings, and pi only loads project resources after the project is trusted — so a project-scoped install stays inert until you trust the project in an interactive session.

## How It Works

The plugin registers three tools and three lifecycle hooks.

```
session_start        ensure the onnx default, index the journal in the background
before_agent_start   inject recent journal entries into the system prompt
agent_settled        extract the turn, summarize it, append it, reindex
```

Capture runs on `agent_settled` rather than `agent_end` because pi may still auto-retry, auto-compact, or drain queued messages after `agent_end`, which would capture the same turn twice.

### Three-layer progressive disclosure

| Layer | Tool | What it returns |
| --- | --- | --- |
| L1 | `memory_search` | Relevant chunks across past sessions |
| L2 | `memory_get` | The full markdown section for one chunk |
| L3 | `memory_transcript` | The original conversation behind that section |

Each journal entry carries an anchor comment recording where it came from:

```markdown
### 17:32
<!-- session:019f98… turn:3950049d transcript:/Users/you/.pi/agent/sessions/…jsonl -->
- User asked what a B+ tree is.
- Pi explained that it is a balanced multi-way search tree…
```

`transcript.py` resolves one root-to-leaf path through the session by walking `parentId`, so branches created by `/fork` or `/clone` never interleave with the live conversation.

### Summarization

Turn summaries fall back through three options:

1. A memsearch-managed provider, when `plugins.pi.summarize.provider` names one
2. pi itself in print mode — the default, matching `provider = "native"`
3. The raw turn text, truncated

## Skills

| Skill | Use it for |
| --- | --- |
| `memory-recall` | Searching past sessions and folding the results into an answer |
| `memory-config` | Diagnosing setup, provider routing, index health |
| `memory-to-skill` | Distilling recurring workflows into reusable skills |

## Configuration

```bash
memsearch config set plugins.pi.summarize.provider openai   # default: native
memsearch config set embedding.provider onnx                # default
```

See the [memory-config skill](skills/memory-config/SKILL.md) for the full key reference, or run `memsearch config list --resolved`.

## Differences from the Claude Code plugin

Two deliberate divergences, both driven by pi's extension model:

- **Recall is tool-driven, not a forked subagent.** pi skills have no `context: fork` equivalent, so `memory-recall` guides the model through the three tools rather than running retrieval in an isolated context.
- **No file watcher.** Like the OpenCode and OpenClaw plugins, the index is refreshed at session start and after each capture. (The Claude Code plugin also skips its watcher under Milvus Lite, where a file lock prevents concurrent access.)

## Troubleshooting

Failures in capture and injection are swallowed so they can never break a session. To see them:

```bash
MEMSEARCH_DEBUG=/tmp/memsearch.log pi
```

Common cases:

- **Journals are written but search is empty** — check `.memsearch/.index-state.json` for `status` and `last_error`, then re-run `memsearch index`.
- **The index will not open** — a Milvus Lite database written by an older release is unreadable by 3.x. Move the `.db` aside and re-index from the markdown, which is the source of truth.
- **Entries contain raw transcript instead of bullet points** — every summarizer fell through. The debug log names the one that failed.

## Development

```bash
npm install
npm test
pi -e .          # load this package for one run, without installing
```
