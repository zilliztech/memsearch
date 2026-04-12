# Changelog - Claude Code Plugin Skill Surface Design

> **Parent Document:** [../design/claude-code-plugin-skill-surface.design.md](../design/claude-code-plugin-skill-surface.design.md)
> **Current Version:** 1.0
> **Session:** 4e792d4b-8876-439b-8c07-2c5d4b04af3a

---

## Version History (Unified)

| Version | Date | Changes | Session ID |
|---------|------|---------|------------|
| 1.1 | 2026-04-12 | **[Added orchestration/front-door wrapper skill direction and baseline `memory-router` skill](#version-11)** | 11c4bd2f-216e-4779-81bf-26d34a4fcaeb |
| | | Summary: Extended the local design from direct-skill expansion to also include a memsearch-first orchestration skill that chooses the correct retrieval path and prevents premature `not found` conclusions. | |
| 1.0 | 2026-04-08 | **[Created local design baseline for expanding memsearch Claude-facing skill surfaces](#version-10)** | 4e792d4b-8876-439b-8c07-2c5d4b04af3a |
| | | Summary: Established a bounded design direction for adding Claude-facing `search`, `expand`, `session-recall`, `stats`, and `config-check` skills before introducing any broader memory-agent surface | |

---

<a id="version-11"></a>
## Version 1.1: Added orchestration/front-door wrapper skill direction and baseline `memory-router` skill

**Date:** 2026-04-12
**Session:** 11c4bd2f-216e-4779-81bf-26d34a4fcaeb

### Changes
- Extended the local design direction to include a Claude-facing orchestration/front-door wrapper skill `memory-router`.
- Defined the wrapper responsibilities: memsearch-first routing, memory-system distinction, bounded retrieval ladder, query reformulation before search, and readiness checks when embedding/config/index health may be the blocker.
- Added `plugins/claude-code/skills/memory-router/SKILL.md` as the initial baseline artifact for this orchestration layer.
- Kept the design scope skill-first and bounded instead of jumping to a larger memory-agent surface.

### Summary
The local skill-surface design now addresses not only missing direct tool entry points, but also the orchestration weakness where an assistant can choose the wrong memory system or conclude `not found` before using the right memsearch path.

---

<a id="version-10"></a>
## Version 1.0: Created local design baseline for expanding memsearch Claude-facing skill surfaces

**Date:** 2026-04-08
**Session:** 4e792d4b-8876-439b-8c07-2c5d4b04af3a

### Changes
- Created `design/claude-code-plugin-skill-surface.design.md` as the local target-state design for expanding Claude-facing memsearch skill surfaces.
- Recorded the current checked limitation that the Claude Code plugin exposes a narrow skill-facing access path relative to the richer underlying CLI capability.
- Defined a skill-first rollout direction for `search`, `expand`, `session-recall`, `stats`, and `config-check`.
- Recorded that a broader memory navigator agent remains a later-only optional surface rather than the first implementation step.

### Summary
Created a bounded design baseline so memsearch plugin development can expand Claude-facing access surfaces in a structured way instead of relying on ad hoc CLI prompting.
