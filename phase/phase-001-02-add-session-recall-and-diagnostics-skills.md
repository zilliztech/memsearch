# Phase 001-02 - Add session recall and diagnostics skills

> **Summary File:** [SUMMARY.md](SUMMARY.md)
> **Phase ID:** 001-02
> **Status:** Planned
> **Design References:** [../design/claude-code-plugin-skill-surface.design.md](../design/claude-code-plugin-skill-surface.design.md)
> **Patch References:** none

---

## Objective

Add bounded `session-recall`, `stats`, and `config-check` skill surfaces.

## Why this phase exists

The current plugin makes session-specific memory retrieval and memsearch diagnostics harder than they need to be from Claude-facing workflows.

## Action points / execution checklist

- [ ] design a session-specific recall skill interface
- [ ] add `session-recall` skill for bounded session-focused lookup
- [ ] add `stats` skill for collection/index health
- [ ] add `config-check` skill for provider/config diagnostics
- [ ] keep diagnostics actionable and concise

## Verification

- session-specific recall works without requiring direct CLI prompting every time
- stats/config surfaces are Claude-facing and bounded
- diagnostics explain the effective config and likely blockers clearly

## Exit criteria

- the plugin exposes bounded session recall and diagnostics as first-class Claude-facing skills
