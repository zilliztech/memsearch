# Skills from Memory

MemSearch can grow a third memory layer on top of your journals: **procedural
memory** — reusable *skills* distilled from the workflows you repeat.

| Layer | Where | What it holds |
| --- | --- | --- |
| Episodic | `.memsearch/memory/*.md` | What happened (raw conversation journals) |
| Semantic | `.memsearch/PROJECT.md`, `.memsearch/USER.md` | What is true (durable project state, user profile) |
| **Procedural** | `.memsearch/skill-candidates/` | **How you do recurring tasks** (candidate skills) |

A skill is an [Agent Skills](https://agentskills.io)-standard `SKILL.md`: a short,
reusable procedure (how to run the app, deploy, debug a class of error) that an
agent can load and follow. Because it follows the open standard, a skill distilled
once is portable across Claude Code, Codex, OpenCode, and other agents.

## Stages

**0** memory journals → **1** candidate (`.memsearch/skill-candidates/`) → **2**
installed (an agent's skill directory). The candidate store is a self-contained
**git repository**, so every edit is a commit you can `git log`, `git diff`, or
`git revert`. Candidates keep evolving there — including ones you have already
installed; the store is the perpetually-updated source, and installing only ever
takes a snapshot out. Candidates are **never** written into an agent's skill
directory automatically.

## Two ways a candidate gets created (0 → 1)

Skill *content* can be generated two ways. Generating content needs a model;
**only this step uses one**. Persisting (`add`) and installing are plain
file/git operations.

**1. Background distillation (automatic, model-driven).** Like the
[advanced maintenance](configuration.md#advanced-plugin-maintenance) tasks, a
`memory_to_skill` task runs on the session-end / `min_interval_hours` cadence,
using the configured provider (default `native`). It mines recent journals for
workflows that **recur at least `min_occurrences` times** and writes them as
candidates. It is deliberately conservative — most runs distil nothing — because
it is unattended. This path is gated by `enabled` (off by default) to avoid
surprise background model calls.

**2. Manual capture (on demand, agent-driven).** When you tell the agent *"make a
skill out of what we just did"*, the **live agent you are talking to** drafts the
`SKILL.md` from its own context — no separate model call, no provider config, and
no recurrence threshold (your explicit request is the signal, so even a one-off is
fine). It persists the result with `memsearch skills add`, which only handles the
slug, standard frontmatter, `meta.json`, and the git commit. This path is **not**
gated by `enabled` — an explicit request is never a surprise. The same skill can
also mine *past* work on demand: it reads the journals and persists what recurs
with `skills add`, again entirely in the agent.

The `memsearch skills distill` CLI runs the model-driven mining standalone, but it
needs an **API provider** — the default `native` provider drives the host agent
and only works from the background pass, not as a bare CLI call.

## Install (1 → 2, always manual)

Review a candidate — optionally inspect its history and edit it — then copy its
current version into an agent's skill directory. Installing is the only thing that
makes a skill agent-visible; re-installing takes a fresh snapshot of the evolved
source.

```bash
memsearch skills list                                   # review candidates (-j for detail)
memsearch skills install <name> --path .claude/skills   # snapshot into a skills directory
```

Each agent reads skills from its own directory:

| Agent | Project dir | Global dir |
| --- | --- | --- |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Codex | `.agents/skills/` | `~/.agents/skills/` |
| OpenCode | `.agents/skills/` | `~/.agents/skills/` |
| OpenClaw | `.openclaw/skills/` | `~/.openclaw/skills/` |

`.agents/skills/` is the shared standard read by Codex, OpenCode, Cursor, and
others — but **not** by Claude Code. `--path` is repeatable, so one skill can be
installed to several agents at once.

## Enable and tune the background pass

Disabled by default, like the maintenance tasks. (Manual capture and explicit
`distill` work whether or not this is enabled.)

```bash
memsearch config set plugins.codex.memory_to_skill.enabled true --project
memsearch config set plugins.codex.memory_to_skill.min_occurrences 3 --project   # default 3; lower = more eager
memsearch config set plugins.codex.memory_to_skill.provider native --project
# Optional: pre-set install targets (otherwise the skill asks you)
memsearch config set plugins.codex.memory_to_skill.paths '[".agents/skills"]' --project
# Optional: custom distillation prompt
memsearch config set prompts.memory_to_skill .memsearch/prompts/memory-to-skill.txt --project
```

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Turn the **background** pass on (manual paths ignore this) |
| `min_occurrences` | `3` | How many times a workflow must recur before background mining distils it |
| `min_interval_hours` | `24` | Minimum gap between background runs |
| `input_dir` | `.memsearch/memory` | Which journals to read |
| `provider` / `model` | `native` | Same routing as the maintenance tasks |
| `paths` | _(empty)_ | Where installed skills are copied; empty = you are asked at install time |

See [Configuration](configuration.md) for how provider/model routing and prompt
overrides work — they are shared with the maintenance tasks.

## The `/memory-to-skill` skill

The plugins install a `/memory-to-skill` skill that drives the whole flow from
natural language and routes by intent: **capture** what you just did (draft → add →
install), **review & install** existing candidates, **distill** from history on
demand, or **configure** the background pass. It never enables the feature, changes
install paths, or installs a candidate without your go-ahead.
