# Codex platform reference

## Plugin version & update

Codex plugin has no independent package/version file. Inspect
`${CODEX_HOME:-$HOME/.codex}/hooks.json` to find the hook source path, then
compare that repository with the latest `zilliztech/memsearch` GitHub release:

```bash
git -C <memsearch-repo> describe --tags --always --dirty
gh release view --repo zilliztech/memsearch --json tagName,publishedAt,url
```

Update source installs with `git pull` plus
`bash plugins/codex/scripts/install.sh`.

Docs: https://zilliztech.github.io/memsearch/platforms/codex/installation/

## Plugin keys

```toml
[plugins.codex.summarize]
enabled = true
provider = ""      # empty/native = Codex native summarizer
model = ""

[plugins.codex.project_review]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/PROJECT.md"

[plugins.codex.user_profile]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/USER.md"

[plugins.codex.memory_to_skill]
enabled = false
min_occurrences = 3   # how many times a workflow must recur before it is distilled
paths = []            # where installed skills are copied; empty = ask the user
```

## Native model defaults

- Native summarize defaults to `gpt-5.1-codex-mini`.
- Native maintenance uses the Codex default unless `plugins.codex.<task>.model` is set.
- `provider = ""` or `native` uses Codex's non-interactive native path.

## Restart guidance

A fresh Codex session is recommended after `hooks.json`, skill, plugin, or
local agent-file changes, because the current session may already have loaded
the old hook/skill state. TOML changes apply on the next capture/recall/index/
maintenance invocation.
