# OpenCode platform reference

## Plugin version & update

OpenCode plugin latest published version comes from
`npm view @zilliz/memsearch-opencode version dist-tags --json`; the source
version is `plugins/opencode/package.json`. Plugin **0.4.0** supports official
OpenCode **>=2.0.32 <3**; plugin **0.3.17** supports V1. The development SDK is
pinned to 2.0.32. Check `opencode --version` and
identify the plugin's actual loaded path and package version from its loading
logs or cache metadata. Registry latest and a workspace package version do not
prove which plugin a running session loaded.

Check the loaded release's documented OpenCode support range before recommending
an update. The `0.3.17` plugin uses the V1 API. A V2-only plugin requires a V2
host; compare the host against the supported range, not numerically against the
plugin version. For a mismatch:

- OpenCode V1 with a V2-only plugin: recommend upgrading OpenCode, or pinning a
  documented V1-compatible plugin release such as
  `"plugin": ["@zilliz/memsearch-opencode@0.3.17"]` while retaining other plugins.
- OpenCode V2 with a V1 plugin: recommend `opencode plugin add
  @zilliz/memsearch-opencode@0.4.0`, or a newer release whose support range includes
  the host. Remove the old MemSearch entry so exactly one remains enabled.

After an authorized plugin change, refresh the relevant plugin cache through
OpenCode's supported mechanism and restart to verify the loaded version. V1 may
reject a V2-only entrypoint before its initialization runs, so its startup checks
and runtime-registered skills cannot be the only troubleshooting entrypoint.
The same guidance must remain accessible in installation documentation or an
independently installed `memory-config` skill.

OpenCode transcript recall reads from OpenCode's SQLite database, while
captured MemSearch memory lives as markdown under `.memsearch/memory/`.

Docs: https://zilliztech.github.io/memsearch/platforms/opencode/installation/

## Transcript migration and existing memories

Existing markdown summaries and `<!-- session:... turn:... db:... -->` anchors
keep their format. Search and expand operate on these memories; L3 transcript
recall also requires the referenced session and turn to remain accessible in
the host's database.

If L3 fails after an OpenCode upgrade, check host/plugin compatibility, database
location and availability, and the specific session/turn lookup before diagnosing
a migration problem. V1 `message`/`part` tables and V2 `session_message` use
different representations; table presence alone does not prove that the
referenced session has been migrated.

When evidence indicates an incomplete host migration, explain the limitation
and direct the user to the applicable
[OpenCode migration guidance](https://opencode.ai/v2/docs/migrate-v1).
The user performs the host migration. Do not migrate or edit the OpenCode
database, rewrite markdown anchors, or reset MemSearch capture state as a recall
fallback. Preserve usable search/expand results and report L3 as unavailable
until the original conversation can be verified. New conversation capture also
depends on supported host data and should be checked separately.

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

- Native summarize uses `plugins.opencode.summarize.model`, then the host-resolved title-agent model, then the host default. V2 migrates `small_model` into the title agent.
- Native maintenance uses OpenCode's default unless `plugins.opencode.<task>.model` is set.
- `provider = ""` or `native` uses stateless `ctx.generate.text`: no session history, child sessions or tools. Native maintenance cannot verify exact commands via transcript tools; do not invent that evidence in Skill candidates.
- Other providers retain the shared API-provider configuration, endpoints, environment-key references, model overrides and prompts. These are MemSearch settings; do not modify OpenCode's provider/auth configuration to diagnose them.

## Restart guidance

Restart OpenCode after host configuration, plugin code or packaged Skill changes.
V2 uses a `plugins` array with exactly one MemSearch source. Skills register at
runtime; do not combine the source entry with an npm entry or an old local plugin
link. TOML changes apply on the next capture/recall/index/maintenance invocation.

Completion events trigger a finite capture helper immediately; a 15-second
recovery scan covers missed events. Pending capture/index work is replayed before
prompt/context/search/expand. The host has a three-second shutdown limit, so a
short exit may leave work for the next activation; unconditional exit-time
inference is not guaranteed. There is no detached V2 daemon to restart, and the
plugin does not manage old daemon processes. Check `.memsearch/opencode-turns.db`
V2 pending/progress tables and `.memsearch/.index-state.json` when diagnosing
capture. Never delete state as a recall fallback.
