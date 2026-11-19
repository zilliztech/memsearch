# OpenCode platform reference (memory-to-skill)

## Config key prefix

`plugins.opencode.memory_to_skill.*`

## Install paths

Each agent reads skills from its own directory: Claude Code `.claude/skills/`;
Codex and OpenCode `.agents/skills/` (the shared standard, also read by Cursor
etc.); OpenClaw `.openclaw/skills/`. Claude Code does **not** read
`.agents/skills/`.

Recommended targets:

- `.agents/skills` — **project-local (recommended)**: a skill from this project's memory is usually most relevant here.
- `~/.agents/skills` — global: available across all your projects.
- a custom path, or several (one skill can be installed to multiple dirs).

Install to multiple paths to cover several agents.

## V2 runtime and native distillation

The V2 plugin registers `memory-recall`, `memory-config`, and
`memory-to-skill` from its packaged files. These built-ins do not require global
Skill symlinks. Candidate installation still uses the configured filesystem
targets above and requires an explicit user request.

Native distillation uses stateless host inference with the task's model override
or host default. It has no tools for transcript verification. The shared prompt
allows general candidates when original evidence is unavailable; never fabricate
exact commands or claim L3 verification from a journal summary.
