# Memory Tools

The Claude Code plugin now exposes six Claude-facing skill surfaces for memory retrieval and diagnostics workflows:
- `memory-recall`
- `memory-search`
- `memory-expand`
- `session-recall`
- `memory-stats`
- `config-check`

These skills sit on top of the same memsearch CLI engine, but they serve different retrieval depths.

---

## Skill Reference

| Skill | What it does | Best use |
|------|---------------|----------|
| `memory-recall` | Progressive recall workflow: search → expand → optional transcript drill-down | When the user asks a natural historical question and Claude should autonomously gather the right amount of context |
| `memory-search` | Direct shortlist search over indexed memories | When you want relevant chunk hashes and concise discovery results without full expansion |
| `memory-expand` | Expand one or more known `chunk_hash` values into full markdown sections | When you already know which chunk(s) you want to inspect in detail |
| `session-recall` | Recall bounded memory context for one explicit session id | When you know the session id and want session-local results without broad recall |
| `memory-stats` | Show collection and index health | When you need chunk counts, embedding dimensions, or quick collection status |
| `config-check` | Summarize effective memsearch config | When provider/config/credential issues need diagnosis |

---

## When to use which skill

### `memory-recall`
Use when the question is broad and Claude should decide how deep to drill.

Examples:
- `/memory-recall what did we decide about Redis TTL?`
- `We discussed this bug last week — what was the fix?`

### `memory-search`
Use when you want targeted search results first.

Examples:
- `/memory-search Redis TTL`
- `/memory-search auth refactor session cookies`

This returns a bounded shortlist with `chunk_hash` values that can be passed to `memory-expand`.

### `memory-expand`
Use when you already have a `chunk_hash` and want the full markdown section.

Examples:
- `/memory-expand abc123def4567890`
- `/memory-expand abc123def4567890 42ff0011aa22bb33`

---

## Recommended workflow

```text
Need broad historical answer
  → memory-recall

Need shortlist first
  → memory-search
  → pick chunk_hash
  → memory-expand
```

This keeps memory access progressive and bounded instead of dumping large memory sections by default.

For diagnostics:
- use `memory-stats` when you need collection/index health
- use `config-check` when retrieval behavior looks wrong or provider config is unclear

---

## Design note

The plugin still uses the same underlying memsearch CLI commands (`search`, `expand`, transcript drill-down) and keeps the main conversation cleaner by running these skills in forked contexts.
