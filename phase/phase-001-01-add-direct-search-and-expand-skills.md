# Phase 001-01 - Add direct search and expand skills

> **Summary File:** [SUMMARY.md](SUMMARY.md)
> **Phase ID:** 001-01
> **Status:** Planned
> **Design References:** [../design/claude-code-plugin-skill-surface.design.md](../design/claude-code-plugin-skill-surface.design.md)
> **Patch References:** none

---

## Objective

Add explicit Claude-facing `search` and `expand` skills to the memsearch Claude Code plugin.

## Why this phase exists

The plugin already has the underlying CLI capability and a progressive retrieval model, but Claude-facing access remains too narrow when only `memory-recall` is exposed as a direct skill surface.

## Action points / execution checklist

- [ ] inspect current plugin skill-loading structure under `plugins/claude-code/skills/`
- [ ] add a direct `search` skill
- [ ] add a direct `expand` skill
- [ ] keep result shape bounded and shortlist-first
- [ ] avoid turning these skills into large dump-by-default surfaces

## Verification

- Claude-facing `search` and `expand` skills are discoverable
- both skills map cleanly to the underlying CLI commands
- output remains bounded and operator-usable

## Exit criteria

- the plugin exposes direct search-layer and expand-layer skills without requiring ad hoc Bash prompting for routine use
