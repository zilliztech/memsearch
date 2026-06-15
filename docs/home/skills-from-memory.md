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

## How it works

There are two stages. Only the second one involves you.

**1. Distill (automatic, background).** Like the
[advanced maintenance](configuration.md#advanced-plugin-maintenance) tasks, a
`memory_to_skill` task runs in the background on the session-end /
`min_interval_hours` cadence. It mines recent journals for recurring multi-step
procedures and writes them as **candidate** skills under
`.memsearch/skill-candidates/`.

That store is a self-contained **git repository**, so every automatic edit is a
commit you can `git log`, `git diff`, or `git revert`. Candidates keep evolving
there over time — including ones you have already installed; the store is the
perpetually-updated source. Candidates are inert: they are **never** written into
an agent's skill directory on their own.

It is deliberately conservative — most runs distil nothing. A workflow becomes a
candidate only when it is a genuine multi-step procedure, recurs at least
`min_occurrences` times, generalizes into a reusable capability, and was not
immediately corrected or abandoned.

**2. Install (manual, human-driven).** You review a candidate — optionally inspect
its history and edit it — then copy its current version into an agent's skill
directory. Installing is the only thing that makes a skill agent-visible.
Re-installing later simply takes a fresh snapshot of the evolved source.

## Enable and tune

Disabled by default, like the maintenance tasks. Configure per platform:

```bash
memsearch config set plugins.codex.memory_to_skill.enabled true --project
memsearch config set plugins.codex.memory_to_skill.min_occurrences 3 --project   # default 3; lower = more eager
memsearch config set plugins.codex.memory_to_skill.provider native --project
# Optional: pre-set install targets (otherwise the skill asks you)
memsearch config set plugins.codex.memory_to_skill.paths '[".codex/skills"]' --project
# Optional: custom distillation prompt
memsearch config set prompts.memory_to_skill .memsearch/prompts/memory-to-skill.txt --project
```

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Turn background distillation on |
| `min_occurrences` | `3` | How many times a workflow must recur before it is distilled |
| `min_interval_hours` | `24` | Minimum gap between background runs |
| `provider` / `model` | `native` | Same routing as the maintenance tasks |
| `paths` | _(empty)_ | Where installed skills are copied; empty = you are asked at install time |

See [Configuration](configuration.md) for how provider/model routing and prompt
overrides work — they are shared with the maintenance tasks.

## Review and install

```bash
memsearch skills list                                   # review candidates (-j for detail)
memsearch skills install <name> --path .claude/skills   # snapshot into a skills directory
```

Different agents read skills from different directories:

| Agent | Project dir | Global dir |
| --- | --- | --- |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Codex | `.codex/skills/` | `~/.codex/skills/` |
| OpenClaw | `.openclaw/skills/` | `~/.openclaw/skills/` |
| OpenCode / Cursor / … | `.agents/skills/` | `~/.agents/skills/` |

`.agents/skills/` is the shared standard read by OpenCode, Cursor, and others —
but **not** by Claude Code. `--path` is repeatable, so you can install one skill
to several agents at once.

## The `/memory-to-skill` skill

The plugins install a `/memory-to-skill` skill that drives this whole flow from
natural language: it checks whether distillation is enabled (and offers to enable
it), lists candidates, asks where to install, and copies the chosen skill out. It
never enables the feature, changes install paths, or installs a candidate without
your go-ahead.
