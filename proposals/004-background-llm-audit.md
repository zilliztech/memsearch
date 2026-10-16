# Proposal 004: Background LLM call audit

> Status: **in progress — core (Python) implemented**; remaining: DSH JS-side
> hook for `dsh-headless` mode, web dock widget.
> Scope: core library + all platform plugins
> Inspired by dsh-mneme `llmAudit` (v0.4.6, on by default there).

## Problem

Every background LLM invocation made by memsearch — turn summarization
(dsh-headless or custom-llm), maintenance tasks (PROJECT.md/USER.md/skills),
and (if accepted) Proposal 001 consolidation — is currently invisible. There
is no way to answer "how many tokens did memory cost me this month?" or
"why did my summary fall back to the unavailable note?". Failures surface
only as the fallback text inside markdown.

## Proposal

Record every background LLM call to a single local append-only JSONL log at
`<memory>/.llm-audit.jsonl` (one line per call):

```json
{"ts": "2026-09-09T12:00:00Z", "source": "dsh-summarize",
 "provider": "openai-codex/gpt-5.6-luna", "mode": "dsh-headless",
 "status": "ok", "duration_ms": 8210, "input_tokens": 1420, "output_tokens": 180,
 "turn": "session-92e3.../3", "error": null}
```

- `source` enum: `dsh-summarize | claude-summarize | codex-summarize |
  opencode-summarize | openclaw-summarize | project-review | user-profile |
  memory-to-skill | consolidate | compact`.
- Failures are recorded with `status=error` + real cause and **never block**
  the feature itself (audit write is best-effort, wrapped in try/except).
- Retention: entries older than `retention_days` (default 90) pruned on
  `memsearch index` startup.
- CLI surface:
  - `memsearch audit --days 30` — table: tokens/calls/failures grouped by
    `source`;
  - `memsearch audit --errors` — last N failures with causes (first-class
    triage tool for the "summary fallback" failure mode documented in
    CLAUDE.local.md).
- DSH web panel (later, separate task): a small read-only widget on the
  existing memsearch dock consuming `memsearch audit --json`.

## Configuration

```toml
[llm_audit]
enabled = true
retention_days = 90
```

## Integration points

- `src/memsearch/audit.py` (new): `record()` + `report()` helpers.
- Summarize paths: `plugins/dsh/scripts/summarize.py` (custom-llm mode),
  dsh-headless wrapper in `plugins/dsh/index.js` (measure via exit + captured
  stderr; token counts best-effort — omit when unavailable),
  `plugins/claude-code/hooks/stop.sh` claude-invocation, opencode daemon.
- Maintenance runner + future Proposal 001 consolidation calls.
- `src/memsearch/cli.py`: `audit` command.

## Testing

- Unit: record/prune/aggregate; failure lines; corrupted-line tolerance.
- E2E (DSH loop from CLAUDE.local.md): complete one turn, verify audit line
  exists and `memsearch audit --days 1` reports it.
