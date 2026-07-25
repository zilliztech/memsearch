---
name: memory-to-skill
description: "Turn workflows from your memsearch memory into reusable skills. Use when the user asks to make/create/extract/distill a skill from what they just did or from past work, review skill candidates, install a distilled skill, or says 'turn this into a skill'. Manages memsearch procedural-memory candidates under .memsearch/skill-candidates/."
allowed-tools: memory_search memory_get memory_transcript read bash
---

You manage memsearch's **procedural memory**: skills distilled from work that
repeats — a third layer beside the daily journals (episodic) and PROJECT.md /
USER.md (semantic). State once that this is memsearch skill distillation, not
pi's own skills system.

Stages: **0** journals → **1** candidate (`.memsearch/skill-candidates/`, a
git-tracked store) → **2** installed (an agent skill directory). Candidates are
never installed automatically; installing is always a human step. A request may
stop at candidate creation or continue to installation after explicit approval —
match the stage the user asked for.

## Intent routing

- "make a skill from what we just did" → **A. Capture now**
- "what skills / review candidates / install X" → **B. Review & install**
- "mine my history / find recurring workflows" → **C. Distill from history**
- "enable / configure / how eager" → **D. Configure**
- Unclear or empty → run **B**'s `list`; if empty, offer A or C

## A. Capture what you just did (0→1)

You already hold the context, so draft the skill yourself rather than invoking
the background distiller. Write a SKILL.md **body** (markdown, no frontmatter):
imperative numbered steps, concrete commands and paths, no secrets,
self-contained.

**Be exact.** You have the live session, so use the real commands and paths, not
approximations. If a detail is uncertain, verify it or keep that step general — a
wrong command is worse than a vague one.

```bash
printf '%s' "## <title>\n\n1. ...\n2. ..." | memsearch skills add \
  --name "<short-slug>" \
  --description "<what it does AND when it should trigger>" \
  --body-file -
```

`add` handles slugging, frontmatter, meta.json, and the git commit — no LLM is
involved. Show the result to the user and install only on explicit approval.

## B. Review & install candidates (1→2)

```bash
memsearch skills status          # candidates whose source changed since install
memsearch skills list            # add -j for sources and installed paths
git -C .memsearch/skill-candidates log --oneline -5 2>/dev/null || true
```

`skills status` compares each candidate's content hash against the hash recorded
at the last install; it does not inspect live skill directories. A pending entry
means the candidate evolved after the last deliberate install.

Skim the candidate body before recommending it. Installing copies it as-is, so
this is the last chance to catch a wrong step. Treat installation as an
interactive checkpoint: show the candidate, apply requested tweaks, and confirm
the destination. If `paths` is a non-empty list, propose those; if it is empty,
ask — do not silently pick a default.

```bash
memsearch config get plugins.pi.memory_to_skill.paths 2>/dev/null || echo "[]"
memsearch skills install <name> --path <approved-path>
```

Afterwards, tell the user to run `/reload` or start a fresh session so pi picks
up the new skill.

## C. Mine history for recurring workflows (0→1)

Read the recent journals in `.memsearch/memory/*.md` yourself and look for
multi-step procedures that recur across several sessions. Only propose
procedures that repeat and generalize, not one-offs.

**Drill into the original before drafting.** Journal bullets are a lossy summary;
the exact commands, flags, and paths live in the original conversation. pi stores
transcripts as JSONL under `~/.pi/agent/sessions/`, and the journal anchor
carries both a `transcript:` path and a `turn:` id. Call `memory_transcript` with
that path and turn id to read the original turns with their tool calls, and write
the skill from that. If a detail cannot be confirmed, keep the step general —
never fabricate a command.

## D. Configure

```bash
memsearch config get plugins.pi.memory_to_skill.enabled 2>/dev/null || echo "false"
memsearch config set plugins.pi.memory_to_skill.enabled true
memsearch config set plugins.pi.memory_to_skill.min_occurrences 3
memsearch config set plugins.pi.memory_to_skill.paths '[".agents/skills"]'
```

`plugins.*` keys are trusted settings: set them globally, never with `--project`.
`enabled` gates only the background pass — `skills add` and `skills install` work
regardless, and history mining (**C**) can always be run on demand.

## Install paths

- `.agents/skills` — project-local, and the shared cross-agent standard
- `~/.agents/skills` — global, available in every project
- `.pi/skills` or `~/.pi/agent/skills` — pi-specific

pi reads `~/.pi/agent/skills/`, `~/.agents/skills/`, project `.pi/skills/`, and
`.agents/skills/`. Other agents differ: Claude Code uses `.claude/skills/` and
does **not** read `.agents/skills/`; OpenClaw uses `.openclaw/skills/`. Install to
several paths when a skill should be visible to more than one agent.

## Guardrails

- Never enable the feature, change install paths, or install a candidate without
  the user's go-ahead.
- Do not hand-edit the store; create candidates through `memsearch skills add` so
  the git-tracked history stays meaningful.
