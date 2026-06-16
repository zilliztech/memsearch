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
and paths, no secrets, self-contained.

**Be exact — do not guess.** You have the live session for what you just did, so use the real commands, paths, and output, not approximations. If a detail is uncertain, verify it (re-read the relevant files or the transcript) or keep that step general — a wrong command is worse than a vague one. Then persist it as a candidate:

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

Before recommending or installing, skim the candidate's body: if a step looks uncertain or loosely summarized, re-check it against the source (open the transcript if needed) or flag it to the user and let them decide — installing copies the candidate as-is, so this is the last chance to catch a wrong step.

Pick one, resolve where to install (ask if unset), then install:

```bash
memsearch config get plugins.codex.memory_to_skill.paths 2>/dev/null || echo "[]"
memsearch skills install <name> --path .agents/skills
```

If the list is **empty**, background distillation is likely off or has not run.
Offer the user a choice: capture from recent work now (**A**), distill from
history (**C**), or enable the background pass (**D**).

## C. Mine history for recurring workflows (0→1)

To pull skills out of past work (not just the current session), read the recent
journals yourself — they live in `.memsearch/memory/*.md` — and look for
multi-step procedures that recur across several sessions. Draft each genuinely
reusable one and persist it with `memsearch skills add` (one call per skill), the
same way as **A**. Use your own judgment: only propose procedures that recur and
generalize, not one-offs from a single day.

**Drill into the original before drafting.** The journal bullets are a lossy summary; the exact commands, flags, and paths live in the original transcript. Each journal entry has an anchor naming the transcript file (`rollout:<file>.jsonl` (Codex uses `rollout:`, usually no `turn:`)). Run `memsearch transcript <file>` (add `--turn <id>` when the anchor has one) to get the original turns **with their tool calls** — it auto-detects the format and includes the executed commands and output. Write the skill from that. If the shown excerpt feels incomplete, skim nearby turns in the same original source before committing to exact commands or paths. Only if that command fails (unknown format) fall back to reading the JSONL directly. If you cannot confirm a detail, keep the step general or omit it — never fabricate.

The background pass mines automatically when enabled, but it can only see the summaries; doing it here on demand lets you read the original transcripts, so the result is more accurate.

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
commands above (`skills add`, `skills install`) always work, and you can mine history (C) directly.

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
