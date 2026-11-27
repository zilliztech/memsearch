# OpenClaw platform reference (memory-to-skill)

## Config key prefix

`plugins.openclaw.memory_to_skill.*`

## Install paths

Each agent reads skills from its own directory: Claude Code `.claude/skills/`;
Codex and OpenCode `.agents/skills/` (the shared standard, also read by Cursor
etc.); OpenClaw `.openclaw/skills/`. Claude Code does **not** read
`.agents/skills/`.

Recommended targets:

- `.openclaw/skills` — this agent's native skill directory
- `.agents/skills` — project-local shared standard
- `~/.agents/skills` — global, available across all your projects
- a custom path, or several (one skill can be installed to multiple dirs)

Install to multiple paths to cover several agents.
