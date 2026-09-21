# Codex platform reference (memory-to-skill)

## Config key prefix

`plugins.codex.memory_to_skill.*`

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
