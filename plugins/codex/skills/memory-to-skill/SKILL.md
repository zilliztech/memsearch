---
name: memory-to-skill
description: "Turn workflows from your MemSearch memory into reusable skills. Use when the user asks to make/create/extract/distill a skill from what they just did or from past work, review skill candidates, install a distilled skill, or 'turn this into a skill'. Manages MemSearch procedural-memory candidates under .memsearch/skill-candidates/, not Codex's own skills system."
---

You manage MemSearch's **procedural memory**: skills distilled from the work you
repeat — a third layer beside the daily journals (episodic) and PROJECT.md /
USER.md (semantic). State once that this is MemSearch skill distillation, not
Codex's built-in skills system.

Stages: **0** memory journals → **1** candidate (`.memsearch/skill-candidates/`,
a git-tracked store that keeps evolving) → **2** installed (an agent skill dir).
Candidates are never installed automatically; installing is always a human step.

## Intent routing

- "make/turn this into a skill", "from what we just did" → **A. Capture now**.
- "what skills / review candidates / install X" → **B. Review & install**.
- "mine my history / find recurring workflows" → **C. Distill from history**.
- "enable / configure / how eager" → **D. Configure**.
- Unclear or empty → run **B**'s `list`; if empty, offer A or C.

## A. Capture what you just did (0→1→2)

You already have the context, so **draft the skill yourself** — do not call the
background distiller for this. Write a SKILL.md **body** (markdown, no
frontmatter): imperative numbered steps for the recurring task, concrete commands
and paths, no secrets, self-contained. Then persist it as a candidate:

```bash
printf '%s' "## <title>\n\n1. ...\n2. ..." | memsearch skills add \
  --name "<short-slug>" \
  --description "<what it does AND when it should trigger — lead with the verbs a user types>" \
  --body-file -
```

`add` handles slugging, standard frontmatter, meta.json, and the git commit — no
LLM is involved. Then show it to the user and install it (see **B**). Finally,
check whether background distillation is on; if not, offer to enable it (so
recurring workflows get captured automatically going forward) — do not force it.

## B. Review & install candidates (1→2)

```bash
memsearch skills list            # add -j for sources / installed paths
```

Pick one, resolve where to install (ask if unset), then install:

```bash
memsearch config get plugins.codex.memory_to_skill.paths 2>/dev/null || echo "[]"
memsearch skills install <name> --path .agents/skills
```

If the list is **empty**, background distillation is likely off or has not run.
Offer the user a choice: capture from recent work now (**A**), distill from
history (**C**), or enable the background pass (**D**).

## C. Distill from history (0→1, model-driven)

```bash
memsearch skills distill --plugin codex --force
```

This is explicit, so it runs even if the background flag is off. It mines recent
journals for workflows that recur at least `min_occurrences` times, writes them as
candidates, and you then review/install via **B**. Most runs add nothing — the bar
is intentionally high.

## D. Configure

```bash
memsearch config get plugins.codex.memory_to_skill.enabled 2>/dev/null || echo "false"
# enable the background pass (do not enable silently)
memsearch config set plugins.codex.memory_to_skill.enabled true --project
# how eagerly history-mining distils (default 3; lower = more eager)
memsearch config set plugins.codex.memory_to_skill.min_occurrences 3 --project
# pre-set install targets (otherwise you are asked at install time)
memsearch config set plugins.codex.memory_to_skill.paths '[".agents/skills"]' --project
```

Note: `enabled` only gates the **background** (session-end) pass. The explicit
commands above (`skills add`, `skills distill`, `skills install`) always work.

## Install paths

- `.agents/skills` — **project-local (recommended)**: a skill from this project's
  memory is usually most relevant here.
- `~/.agents/skills` — global: available across all your projects.
- a custom path, or several (one skill can be installed to multiple dirs).

Each agent reads skills from its own directory: Claude Code `.claude/skills/`;
Codex and OpenCode `.agents/skills/` (the shared standard, also read by Cursor
etc.); OpenClaw `.openclaw/skills/`. Claude Code does **not** read `.agents/skills/`.
Install to multiple paths to cover several agents.

## Guardrails

- Never enable the feature, change install paths, or install a candidate without
  the user's go-ahead.
- Do not hand-edit the store; create candidates with `memsearch skills add` and let
  the git-tracked store at `.memsearch/skill-candidates/` keep history.
