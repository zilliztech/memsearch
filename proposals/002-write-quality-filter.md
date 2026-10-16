# Proposal 002: Pre-write memory quality filter

> Status: draft · Scope: core library (capture path shared by all plugins)
> Inspired by dsh-mneme `memoryQualityFilter` (v0.4.6).

## Problem

Automatic capture writes everything the summarizer emits: meta-comments about
the memory system itself ("[memsearch] Recall available"), ultra-short notes,
near-duplicates of yesterday's note, self-referential type tags. These pollute
the index and dilute hybrid-search recall even when they never get injected.

## Proposal

Score every candidate section **before it is appended** to
`memory/YYYY-MM-DD.md`. The scorer is a **pure function** — no I/O, no shared
state, no LLM — mirroring mneme's design:

Penalties (0–100 start):
- meta-memory vocabulary (talks about the memory plugin itself), −25;
- self-referential agent-verbosity boilerplate ("The user asked… I replied…"), −10;
- content shorter than `min_content_length` chars after normalization, −30;
- high token repetition ratio (> 0.6), −20;
- near-duplicate of a section written in the last 48h (hash-shingle Jaccard
  > 0.8 against the current day file), −40.

Actions:
- `score >= 60` → write normally;
- `30 <= score < 60` → write, but record `quality` in the section anchor
  comment and down-weight at search time (multiply normalized RRF score by
  `quality/100`);
- `score < 30` → do not append; log a one-line skip reason to stderr/DSH log.

Unlike mneme we have no persistent DB, so "archived low quality" becomes
"not written" — the transcript anchor already keeps the raw turn reachable,
so no information is lost (progressive disclosure still works via `expand`).

## Configuration

```toml
[quality_filter]
enabled = true
min_content_length = 40
degrade_threshold = 60
reject_threshold = 30
```

## Integration points

- `src/memsearch/quality.py` (new): `score_section(text, recent_sections)`.
- Capture paths: `plugins/dsh/index.js` summarize-then-append step,
  `plugins/claude-code/hooks/stop.sh` pipeline, and the opencode capture
  daemon — the score call should live in one shared place where possible
  (a small `memsearch quality` CLI subcommand the shell hooks can call, or
  the shared summarize scripts).
- `src/memsearch/store.py`: optional `quality` scalar field + down-weighting
  in the hybrid search scorer.

## Testing

- Unit: each penalty rule; boundary scores; pure-function property tests.
- Regression: fixture capture corpus, verify skipped/degraded distribution is
  sane (< 10% rejected on real conversational turns).
