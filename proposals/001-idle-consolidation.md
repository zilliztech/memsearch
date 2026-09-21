# Proposal 001: Idle LLM memory consolidation (autoDream-style)

> Status: draft · Scope: core library + optional DSH/Claude plugin trigger
> Inspired by dsh-mneme autoDream / Sleep Mode (modusensus/dsh-mneme).

## Problem

`memsearch compact` is a manual, whole-store summarization step. Nothing ever
merges duplicate notes, adjudicates contradictory ones, or archives stale
memory. Over months the markdown store grows monotonically and recall quality
degrades (RRF surfaces superseded chunks alongside current ones).

## Proposal

Add an **automatic, threshold-triggered consolidation pass** over the markdown
store, LLM-driven but validated and idempotent:

1. **Trigger** (configurable, never blocks writes):
   - after N new chunks indexed (default 200) or M chars appended (default 20k)
     since the last run, debounced by 10 min;
   - plus a manual `memsearch consolidate` CLI command.
2. **Candidate selection**: group recent chunks by heading/source; feed the LLM
   a bounded snapshot (newest-first sliding window, like mneme's
   `dreamMaxSnapshotSize`), with per-chunk `source:startLine:endLine` anchors.
3. **Decision list** — the LLM returns a JSON array of decisions only:
   `keep | merge | archive | conflict | update`, each with explicit chunk ids.
4. **Fail-safe application** (no LLM output is trusted):
   - unknown ids, cross-file merges, invalid actions are skipped; the valid
     subset applies; run is marked `degraded`;
   - `merge`: keep the most information-complete section, fold others into it,
     archive losers with a `superseded-by` note;
   - `archive`: move to `<memory>/archive/YYYY-MM.md` — never physical delete
     (markdown stays the source of truth, git history preserved);
   - `conflict`: keep the winner, annotate the loser with provenance;
   - `update`: in-place correction, max 2 per run, 24h age protection.
5. **Audit**: append a run record to `<memory>/.consolidation.log`
   (input snapshot sha256 + decision list + per-id disposition), replayable
   offline; re-running the same decisions is a no-op.
6. **Reindex**: after applying, re-index only touched files.

## Configuration (TOML)

```toml
[consolidation]
enabled = false          # opt-in first release
threshold_chunks = 200
threshold_chars = 20000
delay_ms = 600000
max_tokens = 32768       # mirrors mneme's dreamMaxTokens guidance
prompt = "prompts.consolidate"  # [prompts] section, shared template style
```

LLM route reuses `[llm]` (same providers as `compact`).

## Integration points

- `src/memsearch/consolidate.py` (new): decision parse/validate/apply, audit.
- `src/memsearch/core.py`: hook into `index()` epilogue (fire-and-forget task).
- `src/memsearch/cli.py`: `memsearch consolidate` command.
- `plugins/_shared/prompts/consolidate.txt`: shared template.

## Testing

- Unit: decision validation matrix (invalid ids, cross-type merge, overflow),
  idempotent replay of an audit record, degraded-run marking.
- Golden-file tests on a fixture markdown store.
- Manual E2E in each platform plugin (DSH first: complete turns, confirm
  consolidation fired and collection re-indexed).

## Open questions

- Should the DSH plugin trigger consolidation on `session/disposed` as well?
- Interaction with the per-project collection model (consolidate per
  collection only — cross-project merge is out of scope).
