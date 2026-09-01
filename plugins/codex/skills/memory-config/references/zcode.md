# ZCode platform reference

## Plugin version & update

ZCode plugin has no independent package/version file. Inspect
`~/.zcode/cli/config.json` (the `installed_plugins` / `known_marketplaces`
entries) to find the plugin source path, then compare that repository with the
latest `zilliztech/memsearch` GitHub release:

```bash
git -C <memsearch-repo> describe --tags --always --dirty
gh release view --repo zilliztech/memsearch --json tagName,publishedAt,url
```

Update source installs with `git pull` plus
`bash plugins/zcode/scripts/install.sh`.

Docs: https://zilliztech.github.io/memsearch/platforms/zcode/installation/

## Plugin keys

```toml
[plugins.zcode.summarize]
enabled = true
provider = ""      # empty/native = ZCode native summarizer
model = ""

[plugins.zcode.project_review]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/PROJECT.md"

[plugins.zcode.user_profile]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/USER.md"

[plugins.zcode.memory_to_skill]
enabled = false
min_occurrences = 3   # how many times a workflow must recur before it is distilled
paths = []            # where installed skills are copied; empty = ask the user
```

## Session storage

ZCode stores conversation history in a SQLite database at
`~/.zcode/cli/db/db.sqlite` (override with the `ZCODE_DB_PATH` env var). The
capture hook reads this database directly — there is no JSONL transcript file.
The session id is injected via the `CLAUDE_SESSION_ID` environment variable at
hook invocation time.

## Native model defaults

- Native summarize uses the `claude -p` non-interactive path (same as the
  Claude Code plugin). The model is whatever the `claude` CLI is configured to
  use.
- Native maintenance uses the same `claude -p` path unless
  `plugins.zcode.<task>.model` is set.
- `provider = ""` or `native` uses the ZCode native summarizer.

## Restart guidance

A fresh ZCode session is recommended after `hooks.json`, skill, plugin, or
config file changes, because the current session may already have loaded the
old hook/skill state. TOML changes apply on the next capture/recall/index/
maintenance invocation.
