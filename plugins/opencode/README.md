# MemSearch for OpenCode V2

This source targets the official `@opencode/cli` and `@opencode/plugin` V2 APIs, with standalone TUI capture/recall/recovery tested on **2.0.32 and 2.1.0** and a supported host range of `>=2.0.32 <3`. Development types remain pinned to SDK 2.0.32. It captures completed conversation turns into Markdown and exposes semantic recall across sessions.

**Plugin 0.4.0 supports OpenCode V2 only. V1 users pin `@zilliz/memsearch-opencode@0.3.17`.** Existing Markdown memories and transcript anchors keep their format.

## Installation

Use an existing Node 22 installation managed by nvm (development validation uses 22.23.2), Python 3.11+, and `memsearch` with `--default-collection` support. A normal core installation is `uv tool install 'memsearch[onnx]'`. The plugin can also use `uvx --from 'memsearch[onnx]' memsearch` when the executable is unavailable.

Install the published plugin with OpenCode's package manager:

```bash
opencode plugin add @zilliz/memsearch-opencode@0.4.0
```

Or add it to the V2 configuration:

```json
{
  "plugins": ["@zilliz/memsearch-opencode@0.4.0"]
}
```

For development, run `bash plugins/opencode/install.sh` from this clone to install the pinned development SDK and print the source configuration. Add the absolute plugin directory; the host resolves its exported `index.ts` entry:

```json
{
  "plugins": ["/absolute/path/to/memsearch/plugins/opencode"]
}
```

Keep exactly one MemSearch source enabled. Do not combine this entry with an npm MemSearch plugin or an old local `memsearch.ts` plugin link. Restart OpenCode after changing plugin code or registration. Confirm the loaded package version, path and host version.

## Capture and recovery

Execution completion events immediately wake one finite Python helper. It reads the host's `session_v2` and `session_message` projections **read-only**, ordered by per-session `seq`. Ownership uses the canonical physical checkout root (or exact non-Git directory) and workspace. Host project IDs are diagnostic metadata and may change without changing ownership. Git subdirectories and symlink aliases share their checkout; nested repositories, separate worktrees and different non-Git directories stay isolated. Session metadata is checked before selecting message content. It excludes subagents and copied fork history, synthetic messages, compaction, reasoning and tool output. A streamed assistant response is not complete until its completion timestamp, tool settlement, and terminal boundary agree.

The helper records pending work in versioned tables in `.memsearch/opencode-turns.db`, then summarizes, prepares a durable append, writes `.memsearch/memory/YYYY-MM-DD.md`, advances the sequence cursor, and indexes. Journal append/checkpoint failure and partial writes can be replayed without duplicating a completed append. Unexpected concurrent edits stop repair rather than overwrite journal content. Existing Markdown and `session:` / `turn:` / `db:` anchors retain their format; old sidecar tables are left untouched.

The first activation baselines existing settled history atomically before enabling prompt hooks; incomplete boundaries remain eligible. If that baseline cannot be established, setup fails with a diagnostic. Setup itself does no inference because the host's agents/providers may still be initializing. Execution-event subscription starts after the baseline and registrations; the recovery scan covers events missed during setup. Pending work recovers before a user prompt, context injection, `memory_search`, and `memory_get`. A 15-second scan also covers pending work and missed events while the host is alive.

Officially migrated V2 history has no idle rows. The pinned migration's settled message shape remains eligible for baselining and anchor replay, so a new V2 turn in that conversation can proceed. A following user message alone never proves completion.

The guarantee is **immediate normal capture plus durable recovery before recall**. OpenCode allows only three seconds for shutdown. Cleanup gives the active helper a short grace period, then cancels it; pending inference or indexing resumes on the next activation/recall. It cannot guarantee exit-time inference or a flush after SIGKILL. It does not start, stop, or migrate any old detached daemon.

## Summary configuration

Use the shared `plugins.opencode.summarize` settings. `enabled = false` stops new summaries. Native routing (`provider = ""` or `"native"`) uses stateless `ctx.generate.text`, without creating sessions, running tools, or inheriting the current conversation. Model precedence is task `model` → host-resolved `title` agent model → host default. V2 migrates the old `small_model` choice into the title agent; the plugin does not parse or rewrite host config.

The host default applies when the title agent resolves successfully without a model. A title-agent lookup failure produces a summary-unavailable note without invoking a different model.

Named providers continue through `memsearch summarize --plugin opencode --agent-name OpenCode`, retaining shared provider/model/API endpoint/environment-key overrides. Prompt precedence remains custom `prompts.summarize` → packaged shared prompt → core fallback. Input and output are bounded. Native output must contain bullets; managed providers retain their nonempty plain-text contract. Actual summarizer failures write a short unavailable note with the transcript anchor. Shutdown cancellation leaves work pending; neither path writes raw dialogue as a fallback.

Configured collections override the derived per-project fallback through `--default-collection`; failures to derive a collection stop setup. Embedding configuration is preserved. Only when both global and project MemSearch config are absent, index/search use a per-command ONNX default; nothing writes shared config.

## Tools, context and Skills

| Tool | Purpose |
|---|---|
| `memory_search(query, top_k?)` | L1 JSON results with `chunk_hash` for L2; `top_k` is 1–20. |
| `memory_get(chunk_hash)` | L2 full Markdown section, with transcript anchors. |
| `memory_transcript(session_id, turn_id?, db_path?, limit?, context?)` | L3 original V2 dialogue; limit 1–50, context 0–10. |

Tools validate the requesting session's ownership, including its persisted workspace. L3 honors the database path in the anchor and uses exact or unambiguous turn prefixes. It does not require a capture sidecar. A missing or unmigrated transcript does not invalidate existing search/expand results.

All three tools declare text output for V2 code execution. Search returns a JSON array with `chunk_hash` on each result. Search and expansion run through the finite helper under the same project lock as capture/indexing. Plugin-owned index/search/expand commands also acquire `~/.memsearch/.opencode-cli.lock`, after the project lock, so different checkouts sharing HOME cannot open the local Milvus database concurrently. The HOME lock covers only those CLI operations; native summaries and optional maintenance can run concurrently across projects. Other programs using the same database must coordinate their own access.

A V2 context hook merges recent journal excerpts and recall/candidate hints into `SystemPart` objects without duplicating the memory block. `memory-recall`, `memory-config` and `memory-to-skill` are registered from packaged files with their reference paths. Packaged definitions replace same-name runtime discoveries deterministically; no global Skill files are changed.

Shared PROJECT.md/USER.md maintenance and candidate-only Skill distillation retain their settings, prompts, input digest and due-state. They run only when enabled and due, in a separate finite background helper after capture. Prompt and recall recovery await capture/indexing only; maintenance holds no capture lock and is cancelled on shutdown. Native maintenance uses the task model or host default, through the same stateless inference bridge; managed providers use the shared Python API route. Native maintenance has no tools for L3 verification: exact unverified commands must not be invented in Skill candidates. Installing candidates still requires an explicit user request.

## Migration and validation

OpenCode's [official migration](https://opencode.ai/v2/docs/migrate-v1) is user-owned. MemSearch never migrates the host database or rewrites journal anchors. L3 reports unsupported schema, missing database/session, ownership mismatch, or missing/ambiguous turn IDs; verify the referenced conversation instead of scanning unrelated history.

Development checks:

```bash
npm --prefix plugins/opencode run typecheck
npm --prefix plugins/opencode test
uv run python -m pytest tests/test_opencode_turns.py tests/test_opencode_parse_transcript.py tests/test_maintenance_runner.py tests/test_skills_sync.py
```

Unit/fixture checks do not prove real TUI capture and fresh-session tool-backed recall. Source E2E and published-artifact E2E must be recorded separately.
