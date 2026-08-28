# OpenClaw platform reference

## Plugin version & update

OpenClaw plugin latest published version comes from
`clawhub package inspect memsearch`; the source version is
`plugins/openclaw/package.json`. Update with:

```bash
openclaw plugins install --force clawhub:memsearch
```

then restore required hook permissions and run `openclaw gateway restart`.

Docs: https://zilliztech.github.io/memsearch/platforms/openclaw/installation/

## Plugin keys

```toml
[plugins.openclaw.summarize]
enabled = true
provider = ""      # empty/native = OpenClaw native summarizer
model = ""

[plugins.openclaw.project_review]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/PROJECT.md"

[plugins.openclaw.user_profile]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/USER.md"

[plugins.openclaw.memory_to_skill]
enabled = false
min_occurrences = 3   # how many times a workflow must recur before it is distilled
paths = []            # where installed skills are copied; empty = ask the user
```

## Native model defaults

- Native summarize uses the OpenClaw agent/default model unless overridden.
- Native maintenance also uses the OpenClaw agent/default model unless `plugins.openclaw.<task>.model` is set.
- `provider = ""` or `native` uses OpenClaw's non-interactive native path.

## Restart guidance

Run `openclaw gateway restart` after plugin install/update or hook permission
changes, because the gateway may already have loaded the old plugin state. TOML
changes apply on the next capture/recall/index/maintenance invocation.
