# Claude Code Plugin Skill Surface Design

## 0) Document Control

> **Parent Scope:** memsearch repository
> **Current Version:** 1.0
> **Session:** 4e792d4b-8876-439b-8c07-2c5d4b04af3a (2026-04-08)

---

## 1) Goal

Define the next design direction for the memsearch Claude Code plugin so Claude-facing access to memsearch capabilities becomes more complete and efficient than the current `memory-recall` skill alone.

This design exists inside the memsearch repository and does not replace the upstream project architecture. It records the bounded development direction for the local extension work that will happen under `plugins/claude-code/`.

---

## 2) Problem Statement

The checked plugin surface today is strong on automatic capture but narrow on Claude-facing retrieval entry points:
- hooks provide automatic capture and awareness signals
- the visible Claude-facing skill surface is currently centered on `memory-recall`
- the underlying memsearch CLI already exposes richer commands such as `search`, `expand`, `index`, `watch`, `stats`, `reset`, `config`, and `compact`

This creates practical limits:
- Claude can recall memories, but targeted operator workflows still require direct CLI use more often than ideal
- session-scoped or collection-scoped memory lookup is not exposed as a dedicated Claude-facing surface
- health / config / stats workflows are not surfaced through focused plugin skills
- retrieval quality can be fine, but access ergonomics are narrower than the engine capability

---

## 3) Active Development Direction

### 3.1 Principle

Prefer **skill-first expansion** before adding broader agent orchestration.

Why:
- the current gap is primarily access-surface breadth, not core engine capability
- skill surfaces map naturally to the existing CLI commands
- bounded skills are easier to validate and compose than a larger memory-agent surface introduced too early

### 3.2 Target Claude-facing surfaces

The local development target should add bounded Claude-facing skill surfaces for:
- `memsearch:search` — semantic chunk search
- `memsearch:expand` — expand a chosen chunk hash into full markdown section context
- `memsearch:session-recall` — recall scoped to one session id or bounded session set
- `memsearch:stats` — collection/index health view
- `memsearch:config-check` — effective config / provider / credential / collection diagnostics
- `memsearch:memory-router` — orchestration/front-door wrapper skill that chooses the correct retrieval path before broader fallback behavior

### 3.3 Orchestration direction

The checked local gap is not only missing direct access surfaces.
The larger weakness is that an assistant can still choose the wrong memory system, skip search too early, or conclude "not found" before the correct memsearch retrieval path has been used.

So the next bounded development direction should also add a **wrapper/orchestration skill** with these responsibilities:
- detect when the user is asking a memory/history/session question
- route to the correct memsearch tool first (`memory-search`, `memory-expand`, `session-recall`, `memory-stats`, `config-check`)
- check retrieval readiness first when there is a real chance that embedding/config/index health is the blocker
- enforce a bounded retrieval ladder: search → expand → transcript only when needed
- keep memsearch, Claude auto-memory, transcript files, and current code/docs as distinct systems
- prevent premature "not found" conclusions before the right memsearch path has actually been used
- distinguish true memory absence from retrieval/config failure

### 3.4 Optional later surface

A broader memory navigator agent may be useful later, but it is not the first implementation priority.

Later-only candidate:
- `memsearch:memory-navigator` or equivalent agent surface that can orchestrate search → expand → transcript drill-down in a richer workflow

For the current bounded slice, keep the focus on skill-first expansion plus one orchestration/front-door wrapper skill.

---

## 4) Scope Boundaries

### 4.1 In scope now
- Claude-facing skill expansion for the Claude Code plugin
- improved session-specific retrieval ergonomics
- config / stats / diagnostics skill surfaces
- documentation and phase artifacts that describe the same bounded direction

### 4.2 Not in scope yet
- replacing the current hook model
- introducing a large new agent framework by default
- redesigning the core Python engine
- changing the markdown-as-source-of-truth architecture
- changing the plugin’s automatic capture lifecycle as the primary goal of this wave

---

## 5) Proposed Work Model

### 5.1 Skill-first rollout

Recommended implementation order:
1. add explicit `search` skill
2. add explicit `expand` skill
3. add explicit `session-recall` skill
4. add `stats` and `config-check` skills
5. only then evaluate whether a broader memory navigator agent is still needed

### 5.2 Retrieval posture

The preferred interaction model stays progressive and bounded:
- shortlist first
- expand on demand
- transcript drill-down only when needed
- avoid dumping large amounts of memory text into the main conversation by default

This keeps the plugin efficient and easier to reason about.

---

## 6) Verification Targets

This local design direction is successful when:
- Claude-facing skill surfaces expose more of memsearch’s useful CLI capability
- session-specific retrieval becomes easier without requiring ad hoc Bash prompting every time
- config and health diagnostics become easier to invoke from Claude Code
- the new surfaces remain bounded and do not turn into an uncontrolled memory dump path
- docs / TODO / phase artifacts stay synchronized with the actual implementation slice

---

## 7) Integration

Relevant checked sources in this repo:
- `README.md`
- `CLAUDE.md`
- `plugins/claude-code/README.md`
- `plugins/claude-code/.claude-plugin/plugin.json`
- `plugins/claude-code/hooks/hooks.json`
- `plugins/claude-code/skills/memory-recall/SKILL.md`
- `src/memsearch/cli.py`

---

> Full history: [../changelog/claude-code-plugin-skill-surface.changelog.md](../changelog/claude-code-plugin-skill-surface.changelog.md)
