# Phase 001-04 - Add memory-router orchestration skill

> **Summary File:** [SUMMARY.md](SUMMARY.md)
> **Phase ID:** 001-04
> **Status:** Implemented - Pending Review
> **Session:** 11c4bd2f-216e-4779-81bf-26d34a4fcaeb
> **Design References:** [../design/claude-code-plugin-skill-surface.design.md](../design/claude-code-plugin-skill-surface.design.md)
> **Patch References:** none

---

## Objective

Add a bounded memsearch-first orchestration/front-door wrapper skill so Claude-facing retrieval can choose the correct memsearch path before broader fallback behavior.

## Why this phase exists

The direct skills now exist, but the larger weakness remains in the assistant/operator layer: it can still choose the wrong memory system, skip search too early, or conclude `not found` before the correct memsearch retrieval path has been used.

## Design Extraction

- Source requirement: keep the expansion skill-first and bounded.
- Derived execution work: add a `memory-router` skill that routes between `memory-search`, `memory-expand`, `session-recall`, `memory-stats`, and `config-check`.
- Readiness rule: if embedding/config/index health may be the blocker, check readiness before treating retrieval as genuinely empty.
- Retrieval rule: search first, expand on demand, transcript only when needed.
- Boundary rule: keep memsearch, Claude auto-memory, transcript files, and current code/docs as distinct systems.
- Target outcome: Claude-facing retrieval becomes more reliable than ad hoc assistant behavior.

## Action Points

- [x] Create `plugins/claude-code/skills/memory-router/SKILL.md`.
- [x] Encode memsearch-first routing rules for history/session questions.
- [x] Encode a bounded retrieval ladder.
- [x] Encode query-reformulation guidance before `memory-search`.
- [x] Sync design, changelog, TODO, and phase summary to include the orchestration layer.

## Verification

- `memory-router` skill exists in the plugin package.
- The skill routes memory/history/session questions to the correct memsearch path.
- The wrapper contract makes the checked memory system and retrieval path explicit.
- Governance docs now reflect the orchestration layer, not only the direct skill surfaces.

## Exit Criteria

- The memsearch Claude Code plugin now has both direct retrieval skills and one bounded orchestration/front-door wrapper skill.
- The package remains skill-first and bounded; no larger memory-agent surface is introduced in this phase.
