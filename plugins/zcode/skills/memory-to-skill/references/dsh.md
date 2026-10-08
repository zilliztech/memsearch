# DeepSeek Harness (DSH) platform reference (memory-to-skill)

## Config key prefix

`plugins.dsh.memory_to_skill.*`

## Install paths

Distilled candidates land in `.memsearch/skill-candidates/` (git-tracked) and
are **never installed automatically**. The web profile provides a skill-review
dock; installation is a manual step via `memsearch skills install`.

Resolve the install target from `plugins.dsh.memory_to_skill.paths` in memsearch
config; relative entries resolve against the project dir. When unset, the DSH
default is `~/.agents/skills`, which the `skill-filesystem` provider watches and
loads automatically.

Recommended targets:

- `.agents/skills` — project-local shared standard
- `~/.agents/skills` — global (DSH default), available across all projects
- a custom path, or several (one skill can be installed to multiple dirs)
