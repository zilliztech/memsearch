# DeepSeek Harness (DSH) platform reference

## Plugin version & update

The DSH plugin is the npm package `@zilliz/memsearch-dsh`. Check the published
version:

```bash
npm view @zilliz/memsearch-dsh version dist-tags --json
```

Source version is `plugins/dsh/package.json`. Install/update via the profile
patch mechanism:

```bash
dsh plugin --profile <name> add @zilliz/memsearch-dsh
```

Docs: https://zilliztech.github.io/memsearch/platforms/dsh/installation/

## Two config surfaces

DSH splits config across two surfaces, unlike the other platforms:

1. **MemSearch TOML** (`~/.memsearch/config.toml`) — summarize provider/model,
   Milvus, collection, memory dir, and the maintenance tasks. Uses the
   `[plugins.dsh.*]` prefix.
2. **Plugin-level switches** in the profile's `cordis.patch.yml` — the capture/
   inject/summarize toggles and the summarizer backend, set under the `memsearch`
   row's `config`.

## MemSearch TOML keys

```toml
[plugins.dsh.summarize]
provider = ""      # named [llm.providers.<name>] entry; only used by custom-llm mode
model = ""

[plugins.dsh.project_review]
enabled = false
provider = "native"   # native = a one-shot DSH headless agent
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/PROJECT.md"

[plugins.dsh.user_profile]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/USER.md"

[plugins.dsh.memory_to_skill]
enabled = false
min_occurrences = 3
paths = []          # install targets; default resolves to ~/.agents/skills
```

## Plugin-level switches (cordis.patch.yml)

These are NOT in the MemSearch TOML. They live in the profile patch under the
`memsearch` row's `config`:

```yaml
- id: memsearch
  config:
    captureEnabled: true     # capture completed turns
    injectEnabled: true      # remind the agent to use memory-recall
    summarizeEnabled: true   # summarize turns before writing
    summarizeMode: auto      # auto | dsh-headless | custom-llm
```

## Summarizer backends

- **`auto`** (default) — if `[plugins.dsh.summarize] provider` is set, uses
  `custom-llm`; otherwise `dsh-headless`.
- **`dsh-headless`** — boots a one-shot `dsh --profile headless` agent. The
  sub-agent's model is the deployment's `agent-default-model` from
  `~/.dsh/settings.yaml` (the same selection the Web UI model picker writes).
  **`[plugins.dsh.summarize]` provider/model do NOT apply here** — change the
  model in DSH settings instead.
- **`custom-llm`** — a direct LLM call using `[llm.providers.*]`; provider/model
  come from `[plugins.dsh.summarize]`.

There is no silent fallback between modes: the resolved backend is the one used.
A failed summarization writes a short unavailable note, never a raw transcript
dump.

### Setting up native summaries

During initial setup, if capture and summarization are enabled and the backend
resolves to `dsh-headless`, check how the selected provider gets its API key.
For a key supplied in the DSH service's launch environment, the summary process
inherits it. For a key saved on the DSH **Models** page, filter the output of
`dsh --profile headless --dump-config` locally to show only whether the
`credentials` entry is enabled.

If that entry is disabled, offer to enable the saved keys for all jobs using
the `headless` profile. When the user chooses this option, update or add the
following top-level entry in `$DSH_HOME/profiles/headless/cordis.patch.yml`
(default `~/.dsh/profiles/headless/cordis.patch.yml`). Preserve the other
entries and any existing credential settings.

```yaml
- id: credentials
  name: '@deepseek-ai/dsh-credentials-local'
  disabled: false
```

Recheck the effective entry and verify the next completed turn writes a summary
in the daily Markdown file. Use the same checks if web chat works but summaries
report `MISSING_CREDENTIAL`.

## Native model defaults

- `dsh-headless` and `native` maintenance use the DSH deployment's
  `agent-default-model` (Web UI model picker / `~/.dsh/settings.yaml`).

## Restart guidance

Restart the DSH profile after installing or updating the plugin so the
`memory-recall` skill re-registers and the plugin rows reload. TOML changes
apply on the next capture/recall/index/maintenance invocation; summarizer
backend changes (`summarizeMode`) need the plugin config to reload.

## Command availability

For a missing-command warning, check the profile's `PATH` and explicit
`DSH_CLI`, `MEMSEARCH_CMD`, or `MEMSEARCH_PYTHON` settings. Desktop can register
its bundled CLI through **Manage dsh Command… → Install**; Windows uses
`dsh.cmd`. Preserve quoted paths or JSON argument arrays and restart the profile
after environment changes. Do not guess private Desktop/pnpm paths or silently
change the selected summarization backend. If the command starts but fails,
check its reported error and the selected profile/provider configuration.
