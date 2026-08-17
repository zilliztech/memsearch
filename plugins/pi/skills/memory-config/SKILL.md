---
name: memory-config
description: "Diagnose and configure memsearch memory behavior for the pi plugin. Use when the user asks about memsearch configuration, turn summarization, PROJECT.md/USER.md maintenance, memory directories, index health, provider routing, prompt files, or why memory capture or recall is not working."
allowed-tools: bash read
---

You are a memsearch configuration assistant for the pi plugin. This skill manages
memsearch settings only — it is not pi's own settings or context configuration.
State that distinction once in a diagnostic summary or final answer, not in every
paragraph.

Inspect the user's request. With no concrete ask, run a diagnostic. Otherwise
route with the table below.

## Intent routing

| Request | Go to |
| --- | --- |
| Empty, or "check" | **Diagnose** |
| "Show/get setting" | Read the resolved, global, or project value |
| "Set/enable/disable" | **Configuration**, choosing scope explicitly |
| "Not capturing" / "search is empty" | **Troubleshooting** |
| "Use OpenAI/Gemini/Anthropic/native" | **Provider routing** |
| "PROJECT.md / USER.md / profile / review" | **Advanced maintenance** |
| "Distill a skill" | Tune it here, or use the `memory-to-skill` skill |

Ask before enabling paid providers, changing output paths, re-indexing, deleting
state, or broadening what gets indexed.

## Diagnose

```bash
memsearch config list --resolved     # effective behavior
memsearch config list --global       # ~/.memsearch/config.toml
memsearch config list --project      # ./.memsearch.toml
memsearch --version
```

If `memsearch` is missing, try `uvx --from 'memsearch[onnx]' memsearch --version`.
The CLI ships from PyPI; update with `uv tool install -U "memsearch[onnx]"`.
The pi plugin version lives in `plugins/pi/package.json`; after updating it, run
`/reload` for an auto-discovered extension, or restart pi.

Check the journals and the index:

```bash
MDIR="${MEMSEARCH_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.memsearch}/memory"
ls -la "$MDIR" && tail -80 "$MDIR/$(date +%Y-%m-%d).md"
memsearch stats
cat "$(dirname "$MDIR")/.index-state.json" 2>/dev/null
```

Markdown is the source of truth; the vector index is derived and can always be
rebuilt with `memsearch index`. Transcript drill-down reads pi's own JSONL
sessions under `~/.pi/agent/sessions/`, which are separate from the journals.

## Configuration

Config resolves from built-in defaults, then global config, then project config,
then env refs like `env:OPENAI_API_KEY` and runtime vars such as `MEMSEARCH_DIR`.

Project-local `.memsearch.toml` is restricted. Only low-risk indexing keys are
honored there: `milvus.collection`, `embedding.batch_size`,
`chunking.max_chunk_size`, `chunking.overlap_lines`, `indexing.ignore_files`,
`indexing.exclude`, `watch.debounce_ms`. Everything else — providers, prompts,
plugin automation — must go in global config (omit `--project` on
`memsearch config set`).

pi plugin keys:

```toml
[plugins.pi.summarize]
enabled = true
provider = ""      # empty or "native" = summarize by re-invoking pi itself
model = ""

[plugins.pi.project_review]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/PROJECT.md"

[plugins.pi.user_profile]
enabled = false
provider = "native"
model = ""
min_interval_hours = 24
input_dir = ".memsearch/memory"
output_file = ".memsearch/USER.md"

[plugins.pi.memory_to_skill]
enabled = false
min_occurrences = 3
paths = []         # install destinations; empty = ask the user
```

Empty strings usually mean "use the built-in or native default" rather than
"disabled". Interpret missing fields through `memsearch config list --resolved`,
not by reading raw TOML — older config files are not rewritten on upgrade.

## Provider routing

`provider = ""` or `native` makes the plugin summarize by re-invoking pi in print
mode. Any other value names a provider that must exist under
`[llm.providers.<name>]`:

```toml
[llm.providers.openai]
type = "openai"
model = "gpt-5-mini"
api_key = "env:OPENAI_API_KEY"
```

Model resolution order: `plugins.pi.<task>.model`, then the named provider's
model, then the built-in default. Keep API keys as `env:` refs; never paste them
into chat.

Turn summaries are fine on small, fast models. Advanced maintenance needs better
judgment — set `plugins.pi.project_review.model` and
`plugins.pi.user_profile.model` explicitly when quality matters.

## Advanced maintenance

`project_review` and `user_profile` are disabled by default so nothing makes
surprise background model calls. They run only when enabled, the journal input
changed, and `min_interval_hours` has elapsed. Before enabling, ask which
provider to use, whether 24 hours is the right interval, and whether the default
output paths are acceptable.

Relative `input_dir` / `output_file` resolve against the current project even
when configured globally, so one global setting works across projects.

## Prompt overrides

```toml
[prompts]
summarize = ""          # empty = built-in prompt
project_review = ""
user_profile = ""
memory_to_skill = ""
```

Custom prompt files may use `{{AGENT_NAME}}`, `{{TASK_NAME}}`, `{{PROJECT_DIR}}`,
`{{INPUT_DIR}}`, and `{{OUTPUT_FILE}}`. Use absolute paths in global config;
project prompt paths are not trusted.

## Troubleshooting

- **Nothing captured.** Confirm the journal file for today exists. Capture runs
  on `agent_settled` and skips turns under 50 characters.
- **Capture writes raw transcript instead of bullet points.** The summarizer fell
  through to its last resort. Run the plugin with `MEMSEARCH_DEBUG=/tmp/ms.log`
  and read that file — the failures are otherwise swallowed on purpose.
- **Search returns nothing.** Check `.index-state.json` for `status`,
  `last_error`, and `failed_files`. `degraded` means some files failed;
  `error` means the run did not complete. Re-run `memsearch index`.
- **Index cannot be opened.** A Milvus Lite database created by an older release
  is not readable by 3.x. Move the `.db` aside and re-index from the markdown.
- **Maintenance seems silent.** Check `.memsearch/.maintenance-state.json` for
  `pi.<task>.last_error`.

TOML changes are read lazily, so they usually apply on the next capture, recall,
or index run without restarting pi. After changing the plugin's own code, use
`/reload`.
