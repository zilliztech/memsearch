# Memory Tools

The Claude Code plugin now exposes seven Claude-facing skill surfaces for memory retrieval, diagnostics, and orchestration workflows:
- `memory-recall`
- `memory-search`
- `memory-expand`
- `session-recall`
- `memory-stats`
- `config-check`
- `memory-router`

These skills sit on top of the same memsearch CLI engine, but they serve different retrieval depths.

---

## Skill Reference

| Skill | What it does | Best use |
|------|---------------|----------|
| `memory-recall` | Progressive recall workflow: search → expand → optional transcript drill-down | When the user asks a natural historical question and Claude should autonomously gather the right amount of context |
| `memory-search` | Direct shortlist search over indexed memories | When you want relevant chunk hashes and concise discovery results without full expansion |
| `memory-expand` | Expand one or more known `chunk_hash` values into full markdown sections | When you already know which chunk(s) you want to inspect in detail |
| `session-recall` | Recall bounded memory context for one explicit session id, using memsearch search/expand first whenever possible | When you know the session id and want session-local results without broad recall |
| `memory-stats` | Show collection and index health | When you need chunk counts, embedding dimensions, or quick collection status |
| `config-check` | Summarize effective memsearch config | When provider/config/credential issues need diagnosis |
| `memory-router` | Front-door orchestration wrapper that chooses the correct memsearch path first | When the user is asking a memory/history/session question and the assistant needs to route to the right retrieval or diagnostic tool before broader fallback behavior |

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

The intended retrieval order is:
- try indexed `memsearch search` first
- if the memsearch path is unavailable, clearly nonfunctional, or suspiciously insufficient, use a bounded direct scan of the markdown memory files as fallback

This still returns a bounded shortlist with `chunk_hash` values when available, and those can be passed to `memory-expand`.

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

For session-specific recall:
- prefer `session-recall` when you already know the session id
- even a bare session-id lookup should start with `memsearch search` before any direct markdown/session-anchor reading is attempted
- direct markdown/session-anchor reading is only a bounded fallback when the memsearch path is genuinely insufficient

For front-door routing:
- use `memory-router` when the question is about history/session/recall and the assistant first needs to choose the correct memsearch path
- `memory-router` can also check readiness first when config/index health may be the real blocker instead of genuine memory absence

---

## Design note

The plugin still uses the same underlying memsearch CLI commands (`search`, `expand`, transcript drill-down) and keeps the main conversation cleaner by running these skills in forked contexts.
