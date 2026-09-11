# Claude Code platform reference

## Plugin version & update

Claude Code plugin latest marketplace/source version is in
`plugins/claude-code/.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` in the `zilliztech/memsearch` repo. Check
the latest source manifest with:

```bash
curl -fsSL https://raw.githubusercontent.com/zilliztech/memsearch/main/plugins/claude-code/.claude-plugin/plugin.json
```

For marketplace installs, use `claude plugin marketplace update memsearch-plugins`
then `claude plugin update memsearch`, and restart Claude Code.

Docs: https://zilliztech.github.io/memsearch/platforms/claude-code/installation/

## Plugin keys

```toml
[plugins.claude-code.summarize]
enabled = true
provider = ""      # empty/native = Claude Code native summarizer
model = ""

[plugins.claude-code.project_review]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/PROJECT.md"

[plugins.claude-code.user_profile]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/USER.md"

[plugins.claude-code.memory_to_skill]
enabled = false
min_occurrences = 3   # how many times a workflow must recur before it is distilled
paths = []            # where installed skills are copied; empty = ask the user
```

## Native model defaults

- Native summarize defaults to `haiku`.
- Native maintenance defaults to `sonnet`.
- `provider = ""` or `native` uses Claude Code's non-interactive native path.

## Restart guidance

A fresh Claude Code session is recommended after plugin install/update or
hook/skill file changes, because the current session may already have loaded
the old plugin state. TOML changes apply on the next capture/recall/index/
maintenance invocation.
