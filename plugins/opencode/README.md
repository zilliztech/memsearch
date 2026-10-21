# MemSearch for OpenCode

MemSearch gives OpenCode persistent memory across sessions. Completed conversation turns are summarized into Markdown and indexed for recall. Ask about a past decision or debugging session, and OpenCode can find relevant notes and follow their references to the original conversation.

## Installation

Use Node.js 22+ and Python 3.11+. Install the MemSearch CLI with local embedding support:

```bash
uv tool install 'memsearch[onnx]'
```

Install the published plugin with OpenCode's package manager:

```bash
opencode plugin add @zilliz/memsearch-opencode
```

Or add it to the `plugins` array in `opencode.json`:

```json
{
  "plugins": ["@zilliz/memsearch-opencode"]
}
```

Keep one MemSearch entry alongside your other plugins, then restart OpenCode. The plugin registers its memory tools and Skills automatically. Memories are stored in your project's `.memsearch/memory/` directory.

## Capture and recovery

Execution completion events immediately wake one finite Python helper. It reads the host's `session_v2` and `session_message` projections **read-only**, ordered by per-session `seq`. Ownership uses the canonical physical checkout root (or exact non-Git directory) and workspace. Host project IDs are diagnostic metadata and may change without changing ownership. Git subdirectories and symlink aliases share their checkout; nested repositories, separate worktrees and different non-Git directories stay isolated. Session metadata is checked before selecting message content. It excludes subagents and copied fork history, synthetic messages, compaction, reasoning and tool output. A streamed assistant response is not complete until its completion timestamp, tool settlement, and terminal boundary agree.

The helper records pending work in `.memsearch/opencode-turns.db`, then summarizes, prepares a durable append, writes `.memsearch/memory/YYYY-MM-DD.md`, advances the sequence cursor, and indexes. Journal append/checkpoint failure and partial writes can be replayed without duplicating a completed append. Unexpected concurrent edits stop repair rather than overwrite journal content. Each summary includes a `<!-- session:... turn:... db:... -->` anchor for looking up the original conversation.

The first activation baselines existing settled history atomically before enabling prompt hooks; incomplete boundaries remain eligible. If that baseline cannot be established, setup fails with a diagnostic. Setup itself does no inference because the host's agents/providers may still be initializing. Execution-event subscription starts after the baseline and registrations; the recovery scan covers events missed during setup. Pending work recovers before a user prompt, context injection, `memory_search`, and `memory_get`. A 15-second scan also covers pending work and missed events while the host is alive.

OpenCode allows three seconds for shutdown. Cleanup gives the active helper a short grace period, then cancels it; pending inference or indexing resumes on the next activation before recall. A forced exit can leave work pending.

## Summary configuration

Use the shared `plugins.opencode.summarize` settings. `enabled = false` stops new summaries. Native routing (`provider = ""` or `"native"`) uses stateless `ctx.generate.text`, without creating sessions, running tools, or inheriting the current conversation. Model precedence is task `model` → host-resolved `title` agent model → host default.

The host default applies when the title agent resolves successfully without a model. A title-agent lookup failure produces a summary-unavailable note without invoking a different model.

Named providers use `memsearch summarize --plugin opencode --agent-name OpenCode`, with shared provider/model/API endpoint/environment-key settings. Prompt precedence is custom `prompts.summarize` → packaged shared prompt → core fallback. Input and output are bounded. Native output must contain bullets; managed providers return nonempty plain text. Summarizer failures write a short unavailable note with the transcript anchor. Shutdown cancellation leaves work pending; neither path writes raw dialogue as a fallback.

Configured collections override the derived per-project fallback through `--default-collection`; failures to derive a collection stop setup. Embedding configuration is preserved. Only when both global and project MemSearch config are absent, index/search use a per-command ONNX default; nothing writes shared config.

## Tools, context and Skills

| Tool | Purpose |
|---|---|
| `memory_search(query, top_k?)` | L1 JSON results with `chunk_hash` for L2; `top_k` is 1–20. |
| `memory_get(chunk_hash)` | L2 full Markdown section, with transcript anchors. |
| `memory_transcript(session_id, turn_id?, db_path?, limit?, context?)` | L3 original dialogue; limit 1–50, context 0–10. |

Tools validate the requesting session's ownership, including its persisted workspace. L3 uses the current host database when `db_path` is omitted; an explicit `db_path` selects the database referenced by the anchor. Copy that path exactly when supplying it. A lookup failure in the selected database is reported without retrying against the default database. Turn IDs match exactly or by an unambiguous prefix. L3 does not require a capture sidecar. Search and expansion remain useful when the original transcript is unavailable.

All three tools declare text output for OpenCode's code execution. Search returns a JSON array with `chunk_hash` on each result. Search and expansion run through the finite helper under the same project lock as capture/indexing. Plugin-owned index/search/expand commands also acquire `~/.memsearch/.opencode-cli.lock`, after the project lock, so different checkouts sharing HOME cannot open the local Milvus database concurrently. The HOME lock covers only those CLI operations; native summaries and optional maintenance can run concurrently across projects. Other programs using the same database must coordinate their own access.

A context hook merges recent journal excerpts and recall/candidate hints into `SystemPart` objects without duplicating the memory block. `memory-recall`, `memory-config` and `memory-to-skill` are registered from packaged files with their reference paths. Packaged definitions replace same-name runtime discoveries deterministically; no global Skill files are changed.

The tools are available independently of Skill loading. OpenCode lists the Skills for the model to select or the user to invoke; the full Skill instructions enter the conversation when loaded.

Optional PROJECT.md/USER.md maintenance and Skill distillation use shared settings and prompts. They run only when enabled and due, in a separate finite background helper after capture. Prompt and recall recovery await capture/indexing only; maintenance holds no capture lock and is cancelled on shutdown. Native maintenance uses the task model or host default, through the same stateless inference bridge; managed providers use the shared Python API route. Native maintenance has no tools for L3 verification: exact unverified commands must not be invented in Skill candidates. Installing candidates requires an explicit user request.

## Development

Run `bash plugins/opencode/install.sh` from a source clone to prepare the dependencies. Add the absolute plugin directory to `opencode.json`:

```json
{
  "plugins": ["/absolute/path/to/memsearch/plugins/opencode"]
}
```

Use this directory as the only MemSearch entry, retaining other plugins. Restart OpenCode after source changes and verify the loaded path.

Development checks:

```bash
uv sync --locked
npm --prefix plugins/opencode run typecheck
npm --prefix plugins/opencode test
uv run python -m pytest tests/test_opencode_turns.py tests/test_opencode_parse_transcript.py tests/test_maintenance_runner.py tests/test_skills_sync.py
```

Unit/fixture checks do not prove real TUI capture and fresh-session tool-backed recall. Source E2E and published-artifact E2E must be recorded separately.

For loading or transcript lookup problems, see [troubleshooting](https://zilliztech.github.io/memsearch/platforms/opencode/memory-tools/#troubleshooting).
