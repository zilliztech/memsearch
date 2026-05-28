---
name: memory-config
description: "Diagnose and configure MemSearch memory behavior for the OpenClaw plugin. Use when the user asks about MemSearch configuration, plugin summarization, PROJECT.md/USER.md maintenance, memory directories, index health, provider routing, prompt files, or migration/compatibility questions."
---

You are a MemSearch configuration assistant for the OpenClaw plugin. This skill manages MemSearch settings only. It is not OpenClaw's built-in memory configuration.

Start every user-facing answer with:

> This is MemSearch memory config, not OpenClaw's own memory config.

When this skill is triggered, inspect the user's request text. If there is no concrete request, run a diagnostic. If they ask for a specific setting or change, route the request using the flows below.

## Intent Routing

- Empty request or "check": diagnose current MemSearch setup.
- "Show/get setting": read the requested resolved/global/project value.
- "Set/enable/disable/change": make a safe project-scoped change after confirming ambiguous choices.
- "Not capturing/search empty/no memory": troubleshoot files, config, and index health.
- "Use OpenAI/Gemini/Anthropic/native/model": configure provider routing.
- "PROJECT.md/USER.md/profile/review": configure advanced maintenance.
- "Prompt": explain or configure prompt overrides.

Ask the user before enabling external or paid providers, changing output paths, re-indexing, deleting state, or broadening what gets indexed.

## Diagnose First

```bash
memsearch config list --resolved
memsearch config list --global
memsearch config list --project
```

If `memsearch` is unavailable, try `uvx --from memsearch[onnx] memsearch --version`.

Check memory files:

```bash
MDIR="${MEMSEARCH_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.memsearch}/memory"
ls -la "$MDIR"
find "$MDIR" -maxdepth 1 -type f -name '*.md' | sort | tail -10
tail -120 "$MDIR/$(date +%Y-%m-%d).md"
```

Check index health:

```bash
memsearch stats
```

## Background and Compatibility

Some plugin config fields may be missing or empty. That is usually normal:

- `summarize.enabled`, advanced maintenance, and task-specific provider/model fields are newer settings.
- Existing users' TOML files are not rewritten automatically after package/plugin upgrades.
- Empty strings usually mean "use the built-in or host-native default"; they do not necessarily mean "disabled" or "broken".
- Missing fields should be interpreted through `memsearch config list --resolved`, not by reading raw TOML alone.
- New users who run `memsearch config init` may see more fields than old users because the template includes newer options.
- Advanced maintenance is intentionally disabled by default to avoid surprise background model calls.

## Configuration Logic

Config is resolved from built-in defaults, global config, project config, env refs like `env:OPENAI_API_KEY`, and runtime env such as `MEMSEARCH_DIR`.

Use `memsearch config list --resolved` for effective behavior, `--global` for global overrides, and `--project` for workspace-specific overrides.

Default recommendation:

- Put reusable defaults in global config so users do not repeat setup in every project.
- Put only project-specific overrides in project config.
- Use global config for named LLM providers, common model choices, normal input/output defaults, and shared prompt defaults.
- Use project config for one workspace's enable/disable switches, unusual output files, special intervals, or workspace-specific providers.

Maintenance `input_dir` and `output_file` may be relative even when configured globally. They are resolved from the current workspace/project directory at runtime. For custom prompt paths, prefer absolute paths in global config and relative paths in project config.

OpenClaw plugin keys:

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
```

Provider rules:

- `provider = ""` or `native` uses OpenClaw's non-interactive native path.
- Any other provider value is a name that must exist under `[llm.providers.<name>]`.
- Model resolution order is task-level `plugins.openclaw.<task>.model`, then named provider model, then built-in default.
- API keys should be configured as env refs, not pasted into chat.
- If a raw TOML field is blank, check resolved config before calling it unset or broken.

Common provider examples:

```toml
[llm.providers.openai]
type = "openai"
model = "gpt-5-mini"
api_key = "env:OPENAI_API_KEY"

[llm.providers.anthropic]
type = "anthropic"
model = "claude-sonnet-4-6"
api_key = "env:ANTHROPIC_API_KEY"

[llm.providers.gemini]
type = "gemini"
model = "gemini-3-flash-preview"
api_key = "env:GEMINI_API_KEY"
```

Model guidance:

- Normal turn summaries can use small/fast models. OpenClaw native summarize uses the OpenClaw agent/default model unless overridden.
- Advanced maintenance needs better judgment. OpenClaw native maintenance also uses the OpenClaw agent/default model unless `plugins.openclaw.<task>.model` is set.
- For API providers, defaults are `openai -> gpt-5-mini`, `anthropic -> claude-sonnet-4-6`, and `gemini -> gemini-3-flash-preview`.
- If quality matters more than cost for maintenance, set `plugins.openclaw.project_review.model` and `plugins.openclaw.user_profile.model` explicitly.

Advanced maintenance runs after the plugin wakes it, only when enabled, journal input changed, and `min_interval_hours` elapsed. `PROJECT.md` and `USER.md` are maintenance artifacts by default and are not automatically indexed.

Before enabling advanced maintenance, ask which provider to use, whether the default 24-hour interval is acceptable, and whether `.memsearch/PROJECT.md` / `.memsearch/USER.md` are acceptable output files.

Prompt overrides:

```toml
[prompts]
summarize = ""
project_review = ""
user_profile = ""
```

Empty prompt paths mean use the built-in MemSearch prompts. Custom prompt files may use `{{AGENT_NAME}}`, `{{TASK_NAME}}`, `{{PROJECT_DIR}}`, `{{INPUT_DIR}}`, and `{{OUTPUT_FILE}}`; the runner appends existing output, recent journals, and digest automatically.

Use `memsearch config set` for changes. After changing anything, show the command, the resolved value, and whether a new session is needed.

MemSearch TOML changes are read lazily by the CLI, OpenClaw plugin hooks/tools, and maintenance runner, so values such as `plugins.openclaw.summarize.*`, `plugins.openclaw.project_review.*`, `plugins.openclaw.user_profile.*`, `[llm.providers.*]`, `[prompts]`, `milvus.*`, and `embedding.*` usually apply on the next capture, recall, index, or maintenance invocation. Run `openclaw gateway restart` after plugin install/update or hook permission changes, because the gateway may already have loaded the old plugin state. After any answer, make clear that this is MemSearch memory configuration, not OpenClaw's own memory/config system.

When useful, remind the user that they can either continue using this `memory-config` skill for guided configuration, or manually run `memsearch config init` for global interactive setup, `memsearch config init --project` for project interactive setup, and `memsearch config set/get/list` for direct CLI changes.
