# Installation

## Prerequisites

- [Antigravity CLI](https://antigravity.google/docs/getting-started/) (`agy`) installed
  and signed in. Native summaries use its existing login, including when you
  chat in the desktop app.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.10+.
- The `agy`, `python3`, and `memsearch` commands available to the Antigravity
  process. Start a new app or terminal session after updating your PATH.

Confirm that your account can use the summary model:

```bash
agy -p "Reply with OK" --model gemini-4-hydrogen-low
```

## Install from a checkout

Install the Python core and plugin from the same checkout:

```bash
git clone https://github.com/zilliztech/memsearch.git
cd memsearch
uv tool install --force ".[onnx]"
agy plugin install ./plugins/antigravity
agy plugin list
```

Start a new conversation in your project. The installed package contains its
hooks, skills, prompts, and native helper agent. Antigravity manages the plugin
through its Customizations panel or `/plugin` in the CLI.

For project-local development, place the plugin directory under
`.agents/plugins/memsearch/` in an isolated project. Keep a single active copy
of the plugin in that project.

## Check capture and recall

Tell Antigravity a distinctive project decision. After the reply, allow the
background summary to complete and inspect `.memsearch/memory/YYYY-MM-DD.md`.
The entry should contain a concise summary and a comment linking to its source
conversation.

Open a fresh conversation in the same project and ask it to recover the
decision with `memory-recall`. Ask for the original wording or command output
to exercise transcript recall. The original transcript remains on the machine
where Antigravity recorded it.

## Summary model and provider

The default is native generation with `gemini-4-hydrogen-low`. Override it with
another model available to your account:

```bash
memsearch config set plugins.antigravity.summarize.provider native
memsearch config set plugins.antigravity.summarize.model gemini-4-hydrogen-low
```

To use an existing named API provider, set
`plugins.antigravity.summarize.provider` to that provider's name. The shared
[configuration guide](../../home/configuration.md) describes API keys,
OpenAI-compatible base URLs, and model settings. The summary model is
independent of the model selected for chat.

## Embeddings and Milvus

A fresh plugin setup uses local ONNX embeddings. The initial model download is
cached for later use. Existing global embedding settings are preserved.

Milvus Lite, Milvus Server, and Zilliz Cloud use the same MemSearch configuration
as other plugins. Configure endpoints and credentials in your user-level
configuration, or ask `memory-config` to help. Project-local configuration can
select a collection; endpoint and credential settings belong to the user-level
configuration.

The default collection is derived from the project directory, so agents using
the same project and database can share memories. An explicit collection setting
takes precedence. Use `MEMSEARCH_DIR` to select a different memory directory.

## Background maintenance

Enable the tasks you want:

```bash
memsearch config set plugins.antigravity.project_review.enabled true
memsearch config set plugins.antigravity.user_profile.enabled true
memsearch config set plugins.antigravity.memory_to_skill.enabled true
```

These tasks run when due after conversation capture. Their default minimum
interval is 24 hours, and unchanged input is skipped. Each task has independent
provider, model, and interval settings. Native tasks use Hydrogen Low unless
configured otherwise.

Project review maintains `.memsearch/PROJECT.md`; user profiling maintains
`.memsearch/USER.md`. Skill distillation writes reviewable candidates under
`.memsearch/skill-candidates/`. Use `memory-to-skill` to inspect and install a candidate.

See [advanced memory maintenance](../../home/configuration.md) and
[skills from memory](../../home/skills-from-memory.md) for shared options.

## Troubleshooting

Use `memory-config` to inspect capture settings, the active collection, index
health, and pending background work.

- **No summary:** verify the plugin is enabled, `agy` is reachable from the app,
  and the configured summary model succeeds with `agy -p`. Check the project's
  `.memsearch/.antigravity/` state for pending jobs and errors.
- **Notes exist but search misses them:** inspect `.memsearch/.index-state.json`
  and confirm the embedding provider and database are reachable. The Markdown
  notes remain available while indexing is retried.
- **Configuration reports an unknown platform:** install the core from the same
  checkout as the plugin using the command above.
- **Original conversation is unavailable:** the Markdown summary can still be
  recalled. Transcript drill-down requires the source file named in its anchor.
