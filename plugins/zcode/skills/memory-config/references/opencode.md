# OpenCode platform reference

## Plugin version & update

OpenCode plugin latest published version comes from
`npm view @zilliz/memsearch-opencode version dist-tags --json`; the source
version is `plugins/opencode/package.json`. If `~/.config/opencode/opencode.json`
pins a version, update the pin; otherwise restart OpenCode after package
refresh.

OpenCode transcript recall reads from OpenCode's SQLite database, while
captured MemSearch memory lives as markdown under `.memsearch/memory/`.

Docs: https://zilliztech.github.io/memsearch/platforms/opencode/installation/

## Plugin keys

```toml
[plugins.opencode.summarize]
enabled = true
provider = ""      # empty/native = OpenCode native summarizer
model = ""

[plugins.opencode.project_review]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/PROJECT.md"

[plugins.opencode.user_profile]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/USER.md"

[plugins.opencode.memory_to_skill]
enabled = false
min_occurrences = 3   # how many times a workflow must recur before it is distilled
paths = []            # where installed skills are copied; empty = ask the user
```

## Native model defaults

- Native summarize uses OpenCode `small_model`, then its configured model/default behavior.
- Native maintenance uses OpenCode's default unless `plugins.opencode.<task>.model` is set.
- `provider = ""` or `native` uses OpenCode's non-interactive native path.

## Restart guidance

Restart OpenCode after `opencode.json` or plugin package changes; if capture
behavior still looks stale after TOML edits, restart OpenCode or the capture
daemon. TOML changes apply on the next capture/recall/index/maintenance
invocation.
