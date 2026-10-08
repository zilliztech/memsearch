# ZCode platform reference (memory-to-skill)

## Config key prefix

`plugins.zcode.memory_to_skill.*`

## Install paths

Each agent reads skills from its own directory: Claude Code `.claude/skills/`;
Codex and OpenCode `.agents/skills/` (the shared standard, also read by Cursor
etc.); OpenClaw `.openclaw/skills/`. ZCode reads skills from
`~/.zcode/cli/plugins/local/` (local plugins) and from the installed plugin
cache.

Recommended targets:

- `~/.zcode/cli/plugins/local/<name>/skills` — ZCode's native plugin directory
- `.agents/skills` — project-local shared standard
- `~/.agents/skills` — global, available across all your projects
- a custom path, or several (one skill can be installed to multiple dirs)

Install to multiple paths to cover several agents.
