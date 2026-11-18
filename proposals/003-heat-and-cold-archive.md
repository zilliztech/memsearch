# Proposal 003: Heat decay and cold-memory archival

> Status: draft · Scope: core library (index + search ranking)
> Inspired by dsh-mneme heat model (v0.7.0 / restored v0.7.20) and Sleep
> Mode phase 2 (archival demotion).

## Problem

All indexed chunks rank equally regardless of age or usage. A decision from
six months ago that was never recalled competes with yesterday's active
context. Milvus has no notion of "this memory is cold", so stale chunks keep
surfacing in top-k.

## Proposal

1. **Heat per chunk** (power-law decay, mneme's formula):
   `H = 1 / (1 + λ·Δt)^α`, `Δt` = days since last touch, defaults
   `λ = 0.05`, `α = 2`. "Touch" = returned in a search result (recall) or
   re-written by capture. Per-type half-lives: `decision` decays slowest,
   `history` fastest (config table below).
2. **Storage**: a `heat` FLOAT + `last_accessed` field on each chunk in
   Milvus (schema migration; Lite and Server both support adding fields on
   re-create — markdown stays the source of truth, so a full reindex is an
   acceptable migration path).
3. **Ranking**: multiply normalized RRF score by `0.5 + 0.5·H` — cold chunks
   sink smoothly, never fully banned (explicit high-BM25 matches still win).
4. **Cold archival** (maintenance task, off by default):
   - not recalled in 30 days → chunk excluded from search but its section
     stays in markdown untouched (soft, index-level only);
   - 90 days → move section to `<memory>/archive/YYYY-MM.md` (with
     `memsearch expand` still resolving via archive path);
   - archival runs inside the Proposal 001 maintenance pass; dual protection
     (age AND heat < 0.05) to avoid demoting recently-written-but-unrecalled
     reference notes.

## Configuration

```toml
[heat]
enabled = false        # opt-in; OFF default preserves current ranking
lambda = 0.05
alpha = 2.0
[heat.half_life_days]
decision = 180
preference = 120
project = 90
history = 30
[cold_archive]
enabled = false
demote_days = 30
archive_days = 90
min_heat = 0.05
```

## Integration points

- `src/memsearch/heat.py` (new): decay math + touch tracking.
- `src/memsearch/store.py`: schema fields, touch-on-recall after hybrid
  search, ranking multiplier.
- `src/memsearch/scanner.py`: include `<memory>/archive/` with a `archived`
  flag so `expand` keeps working.

## Testing

- Unit: decay curve values, half-life table, dual-protection gating.
- Search integration: cold vs fresh chunk ordering; explicit keyword override.
- Migration: reindex round-trip preserves heat defaults.

## Open questions

- Should `watch` mode update heat, or only explicit `search` calls (DSH
  injects searches every turn — that alone may keep everything warm)?
