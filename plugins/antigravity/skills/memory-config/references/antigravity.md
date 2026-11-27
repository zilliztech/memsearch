# Antigravity

Use `plugins.antigravity.<task>.*` for `summarize`, `project_review`,
`user_profile`, and `memory_to_skill`. Summarization defaults to native
`gemini-4-hydrogen-low`; each maintenance task uses the same default and accepts
its own model override or a named API provider under `llm.providers`.
Maintenance is opt-in and defaults to a 24-hour interval with changed inputs.

Inspect individual settings with `memsearch config get <key>`. Avoid printing
whole configurations or credentials. Check the host with `agy --help` and the
bundle with `agy plugin validate /path/to/plugins/antigravity`.

This integration initially requires core installed from its source checkout:
`uv tool install --force '/path/to/memsearch[onnx]'`. Use the same checkout for
the plugin. Do not replace it with a published release that lacks Antigravity
config and transcript support. No automatic package install occurs in hooks.

Run recall and index diagnostics through the plugin's `scripts/runtime.py cli
--project-dir /absolute/workspace -- <memsearch command>` wrapper. It supplies
the ONNX first-use default and the workspace's derived collection while
preserving explicit trusted embedding, URI, and collection configuration.
Hooks receive the workspace in `workspacePaths`; their cwd is the plugin root.
With multiple mounted workspaces, the host payload's `cwd` selects its containing
workspace root (the most specific root when mounts overlap). If `cwd` is absent
or outside the mounted workspaces, the first valid workspace is the fallback.

Memory lives under `MEMSEARCH_DIR` or `<workspace>/.memsearch`. Relative
`MEMSEARCH_DIR` resolves from the workspace. Default journal input, PROJECT.md,
USER.md, candidate skills, and checkpoints follow that memory root. Custom
maintenance paths retain the shared project-relative behavior.

The worker journals before indexing. Inspect `.antigravity/jobs/*.json` under
the memory root for `stage`, `last_error`, and the safe `last_error_reason`;
`.index-state.json` records index health. For an invalid native model, correct
`plugins.antigravity.summarize.model` first. For indexing errors, restore the
configured backend; the saved Markdown will be indexed without another summary.
A new session retries pending work automatically, or run:

```bash
python3 /path/to/plugin/scripts/runtime.py worker --project-dir /absolute/workspace
```

Offline maintenance uses the same opt-in, interval, input, and output settings:

```bash
python3 /path/to/plugin/scripts/runtime.py maintenance --project-dir /absolute/workspace
```

`--force` bypasses intervals and unchanged-input skips for enabled tasks.
Native helpers use the existing Antigravity login, an isolated workspace, and
a bundled tool-free agent with MCP and customization inheritance disabled.
Maintenance can request up to three structured read-only transcript/expand
commands through the shared bridge. Transcripts must match supplied journal
anchors; expand uses the workspace collection. No general shell is exposed.
Local Lite access is serialized by canonical database path across Antigravity
workspaces; remote Server and Unix socket requests remain concurrent. If a
local read times out waiting for an active index, retry after it finishes.
`MEMSEARCH_ANTIGRAVITY_SETTINGS` passes a per-run `agy --settings` JSON object
or file. It never changes shared authentication or installed plugins.

Restart the host after changing plugin assets. TOML settings apply on the next
worker or CLI invocation. Use the installed plugin's memory-recall skill for
search → expand → transcript; its wrapper keeps ordinary searches scoped.
