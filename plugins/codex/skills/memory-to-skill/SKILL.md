---
name: memory-to-skill
description: "Turn recurring workflows in your MemSearch memory into reusable skills. Use when the user asks to create/extract/distill a skill from past work or memory, review skill candidates, install a distilled skill, or asks 'make a skill out of what we have been doing'. Manages MemSearch procedural-memory candidates under .memsearch/skill-candidates/, not Codex own skills system."
---

You manage MemSearch's **procedural memory**: candidate skills distilled from the
project's memory journals. This is the third memory layer, alongside the daily
journals (episodic) and PROJECT.md / USER.md (semantic).

State once in your summary that this is MemSearch skill distillation, not Codex's
built-in skills system. Do not repeat that on every line.

Two stages, and you only ever drive the second one:
- **Distill (automatic, background):** MemSearch watches recent journals and writes
  *candidate* skills into `.memsearch/skill-candidates/` (a git repo), and keeps
  evolving them there over time. Every entry — even ones already installed — stays
  a perpetually-updated draft. You never edit that store blindly; it is git-tracked.
- **Install (this skill, human-driven):** the user reviews a candidate and you copy
  its current version into agent skill directories. Installing is the only path that
  makes a skill agent-visible, and re-installing is how an installed skill gets
  updated — the store keeps evolving; install takes a fresh snapshot.

## Intent routing

Inspect the user's request:
- No specific request, "what skills / review candidates" -> **List candidates**.
- "make/extract/distill a skill now", "from what we just did" -> **Distill on demand**, then List.
- "install / publish / turn X into a real skill / update the installed skill" -> **Install**.

## 1. Check the feature is enabled

```bash
memsearch config get plugins.codex.memory_to_skill.enabled 2>/dev/null || echo "false"
```

If this is not `true`, background distillation is **off**. Tell the user, and offer
to turn it on (do not enable it silently). On their confirmation:

```bash
memsearch config set plugins.codex.memory_to_skill.enabled true --project
```

Mention they can tune how eagerly skills are extracted with
`plugins.codex.memory_to_skill.min_occurrences` (default 3 — how many times a
workflow must recur before it becomes a candidate). Lower = more eager.

## 2. List candidates

```bash
memsearch skills list
```

Show candidate names, status (candidate / installed), how often each recurred, and
the one-line description. Use `memsearch skills list -j` for structured detail
(sources, installed paths).

## 3. Distill on demand (optional)

If the user wants to extract right now rather than wait for the background pass:

```bash
memsearch skills distill --plugin codex --force
```

Then list again. Most runs add nothing — that is expected; the bar for a reusable
skill is intentionally high.

## 4. Install a candidate

Installing copies a candidate's current `SKILL.md` into one or more skill
directories. Before installing you may review the candidate, inspect its history
(`git -C .memsearch/skill-candidates log -- <name>/SKILL.md`), and — with the user's
guidance — edit `.memsearch/skill-candidates/<name>/SKILL.md` to taste. Those edits
are committed and then snapshotted out.

First resolve **where** to install:

```bash
memsearch config get plugins.codex.memory_to_skill.paths 2>/dev/null || echo "[]"
```

If this is empty (`[]`), **do not guess** — ask the user where to install, then
persist their choice. Offer these options and explain the trade-off:
- `.codex/skills` — **project-local (recommended)**: scoped to this repo; a skill
  distilled from this project's memory is usually most relevant here.
- `~/.codex/skills` — global: available across all your projects.
- a custom path, or several paths (one skill can be installed to multiple dirs).

Note for cross-agent users, each agent reads skills from its own directory:
Claude Code `.claude/skills/`, Codex `.codex/skills/`, OpenClaw `.openclaw/skills/`,
and the shared `.agents/skills/` standard (read by OpenCode, Cursor, etc.) — but
**not** by Claude Code. To cover several agents, install to multiple paths.

Persist the chosen paths (example for project-local), then install:

```bash
memsearch config set plugins.codex.memory_to_skill.paths '[".codex/skills"]' --project
memsearch skills install <name> --path .codex/skills
```

`--path` is repeatable for multiple destinations. After installing, tell the user the
installed location(s) and that the skill is now agent-visible.

## Guardrails

- Never enable the feature, change install paths, or install a candidate without the
  user's go-ahead.
- Edit candidates only under the user's guidance, and only via the git-tracked store
  at `.memsearch/skill-candidates/`. History (and revert) is available via git there.
