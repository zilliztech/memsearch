# memsearch — WorkBuddy Plugin

Automatic semantic memory for WorkBuddy (CodeBuddy) — captures each finished turn, summarizes it into daily Markdown journals, and indexes them into Milvus for cross-session recall.

Built on the [memsearch](https://github.com/zilliztech/memsearch) CLI backend. All heavy lifting (summarization routing, embedding, indexing) is delegated to `memsearch`; this plugin is a thin, hook-driven compat layer.

## How the Pieces Fit Together

```text
WorkBuddy lifecycle events
        │  stdin: hook payload JSON
        ▼
hooks/hooks.json ──► scripts/handler.py  (single-file dispatcher)
        │                │
        │                ├─ SessionStart ──► status line + recent-memory preview
        │                │                   + background one-shot index
        │                │                   (or watch daemon, opt-in)
        │                │                   + lag-window hint (.last-index-completed)
        │                ├─ Stop/SubagentStop ──► parse.py last-turn extraction
        │                │                        → memsearch summarize (stdin, 110s)
        │                │                        → append memory/YYYY-MM-DD.md
        │                │                        → memsearch index → write timestamp
        │                └─ UserPromptSubmit ──► search top-2 memories ──► inject
        │                                        (marker fallback on any failure)
        ▼
memsearch CLI ──► ~/.memsearch/config.toml (global: embedding, llm.providers,
                  plugins.openclaw.summarize) + Milvus (Lite file or Zilliz Cloud)
```

## Quick Start

### Prerequisites

- `memsearch` CLI on `PATH` (`pip install memsearch`)
- Global config `~/.memsearch/config.toml` with an embedding provider and at least one `[llm.providers.<name>]` entry (type + model)
- Summarize routing via the openclaw slot (WorkBuddy has no native plugin key yet):

```bash
memsearch config set plugins.openclaw.summarize.provider <name>
memsearch config set plugins.openclaw.summarize.enabled true
```

### Install

Place this plugin into a WorkBuddy marketplace directory, then restart WorkBuddy once to load `hooks/hooks.json`:

```bash
# example: copy the plugin into a marketplace
cp -r . "<marketplace-dir>/memsearch-workbuddy"
```

`hooks.json` changes require a WorkBuddy restart; `scripts/*.py` edits hot-reload without one.

## How It Works

### Hook Summary

| Hook | Timeout | What It Does |
|------|---------|--------------|
| **SessionStart** | 10s | Status line (summarize route + provider/model), inject recent-memory preview as `additionalContext`, skills hint when candidates exist, fire detached one-shot index (skip-if-running via `.index.pid`) — or start the watch daemon when `MEMSEARCH_WB_WATCH=1` (server mode only), lag-window hint when inside the freshness window |
| **UserPromptSubmit** | 10s | For prompts ≥ 10 chars: `memsearch search -k 2 -j` against the project collection (6s budget), inject top-2 chunks as `additionalContext`; any failure falls back to the `"[memsearch] Memory available"` marker |
| **Stop** | 120s | Parse last turn → summarize → append daily `.md` (lazy `## Session` heading + anchor) → index → write `.last-index-completed` → fire detached maintenance (due-state throttled) |
| **SubagentStop** | 120s | Same pipeline as Stop |
| **PreCompact** | 10s | Pass-through (`{"continue": true}`) |

### What Each Hook Does

#### SessionStart

1. **Resolves the summarize provider** by reading `~/.memsearch/config.toml` directly (no CLI call; never echoes secrets). Missing provider produces a `NOT CONFIGURED` status instead of silent degradation.
2. **Injects cold-start context**: up to 2 most recent daily journals, 40 lines each, headings + `-` bullets only (mirrors the claude-code plugin's awk filter).
3. **Skills hint**: runs `memsearch skills status --hint` (5s timeout) only when `.memsearch/skill-candidates/` exists; empty output means no hint (contract-compatible with the claude-code plugin).
4. **Background index**: spawns a detached `handler.py --index-and-stamp` child; a `.index.pid` liveness probe makes repeat SessionStarts skip while one is running. The child removes the pidfile and stamps `.last-index-completed` on completion. (Replaced by the watch daemon when `MEMSEARCH_WB_WATCH=1` — see below.)
5. **Lag-window hint**: see below.

#### Stop / SubagentStop

1. **Guards**: `stop_hook_active=true`, `MEMSEARCH_DISABLE=1`, missing transcript, or transcript < 3 lines all exit silently with `{"continue": true}`.
2. **Extracts the last real turn** via `parse.py`: reverse-scans the transcript for the last user message, unwraps `<user_query>`, strips system-reminder/user-context blocks, dedups and truncates file-history snapshots (20 paths + `…(+N more)`), and emits `[User]`/`[Assistant]` labeled text.
3. **Summarizes** by piping the turn to `memsearch summarize --plugin openclaw --agent-name WorkBuddy` (stdin, 110s timeout). On any failure (CLI missing, no provider, timeout, empty output) a fallback bullet is written instead: `- Memory summary unavailable: <reason>; transcript content was omitted. Use the transcript anchor for progressive disclosure.` — the memory entry is never skipped.
4. **Appends the daily journal**: creates `.memsearch/memory/YYYY-MM-DD.md` on demand; first turn of a session gets a `## Session HH:MM` heading; every turn gets `### HH:MM` plus an HTML anchor `<!-- session:<id> turn:<uuid> transcript:<path> -->`.
5. **Indexes immediately**: `memsearch index .memsearch/memory -c <derived-collection>` (300s timeout), then writes `.last-index-completed`.
6. **Fires maintenance** (detached, skip-if-running via `.maintenance.pid`): due tasks (`project_review` / `user_profile`) plus `memory_to_skill` skill distillation. See "Memory Maintenance" below.

#### UserPromptSubmit

1. **Skips short prompts** (< 10 chars) with a bare `{"continue": true}`.
2. **Searches the project collection**: `memsearch search <prompt> -c <derived-collection> -k 2 -j` (query truncated to 500 chars; 6s timeout inside the 10s hook budget).
3. **Injects hits as context**: a numbered `[memsearch] 相关历史记忆` list — `(memory-file › heading) content` with whitespace collapsed, 400 chars per hit — via `hookSpecificOutput.additionalContext`; `systemMessage` reports the hit count.
4. **Never blocks**: CLI missing, timeout, non-zero exit, invalid JSON, or zero hits all fall back to the plain `"[memsearch] Memory available"` marker.

The per-project collection name replicates `scripts/derive-collection.sh` byte-for-byte: `ms_<sanitized-basename>_<sha256[:8]>`, where the hash input is the MSYS-form absolute path (`D:\a\b` → `/d/a/b`). This keeps data continuity with previously indexed projects.

## Memory Maintenance (opt-in, shared backend engine)

Stop spawns a detached `handler.py --maintenance` child that delegates to the backend's own engine (`memsearch.maintenance.run_due_tasks` + `memsearch.skills.distill`) — the same machinery as upstream's `_shared/scripts/maintenance_runner.py`, minus the native-host-CLI branches WorkBuddy can't use:

- **Config routes through the openclaw slot**: the backend's platform whitelist (`claude-code`/`codex`/`opencode`/`openclaw`/`dsh`) has no `workbuddy`, so tasks read `[plugins.openclaw.project_review|user_profile|memory_to_skill]` — same borrowing convention as `plugins.openclaw.summarize`.
- **Provider**: set `provider = "siliconflow"` (or any `[llm.providers.*]` name). `native` has no meaning for WorkBuddy (no headless CLI) and falls back to the `plugins.openclaw.summarize` provider automatically.
- **Throttling is free**: `min_interval_hours` (default 24) due-state in `.memsearch/.maintenance-state.json` makes non-due runs near no-ops; per-task `.maintenance-openclaw-<task>.lock` files prevent overlap.
- **Prompts**: default to the sibling `_shared/prompts/*.txt` (same relative layout as upstream `plugins/_shared`); override globally via `[prompts]` keys.
- **Output**: `PROJECT.md` / `USER.md` inside the memory dir; distilled candidates under `.memsearch/skill-candidates/` (git-backed store; installing into an agent's skills dir stays a human step).
- **Provider/model caveat**: text-output tasks (project_review / user_profile) work fine with DeepSeek-V3.2, but memory_to_skill invites tool calls and DeepSeek's native DSML function-call markup can leak into `content` as text (endpoint doesn't convert it to structured `tool_calls`) → JSON parse error. Remedy: pin that one task to a tool-clean model — `memsearch config set plugins.openclaw.memory_to_skill.model Qwen/Qwen3.5-35B-A3B` (tested: emits raw JSON directly; Qwen2.5-32B also works but fences JSON; Qwen3-Omni-30B-A3B-Instruct and Qwen2.5-7B both fail). Task errors are recorded in due-state and retried per `min_interval_hours` — the hook never blocks.
- **Constraint-decoding is the better fix (upstream OPEN)**: `benchmarks/siliconflow/probe_json_constrained.py` shows DeepSeek-V3.2 emits **clean, tool_calls=0 JSON** (3/3 stable) under SiliconFlow's `response_format: {type: json_schema, json_schema: {…}}` — it disables tools and forces schema-valid output, eliminating the DSML leak outright. memsearch's `_run_openai_with_tools` hard-codes `tools` + no `response_format`, so this needs upstream support for a per-provider custom request body before it can replace the model-pin above.

## The Lag-Window Hint

Zilliz Cloud serverless has eventually-consistent collection statistics: right after indexing, `memsearch search` can silently return zero hits for ~15 minutes even though the data is queryable (row_count lag). To make this window visible without any RPC:

- Stop writes `.memsearch/.last-index-completed` (epoch seconds) **only after a successful index**.
- SessionStart reads that single file; if its age is within `MEMSEARCH_WB_LAG_WINDOW` (default **1200s**), the status line gains: `远端索引统计追平中（上次索引完成于 N 分钟前），新记忆可能暂时查无结果……通常 ≤20 分钟自愈`.

Pure file read, non-blocking, zero cost outside the window.

## Watch Daemon (opt-in)

Set `MEMSEARCH_WB_WATCH=1` to run a resident `memsearch watch <memory> -c <derived-collection>` instead of the one-shot background index — external edits to `memory/*.md` get re-indexed continuously, not just at turn end.

- **Server mode only**: when `milvus.uri` is http(s) the daemon starts detached; with Milvus Lite it is skipped (the local `.db` file lock conflicts with watch — same rule as the claude-code plugin) and the one-shot index remains the fallback.
- **Lifecycle**: pid in `.memsearch/.watch.pid` with a cross-platform liveness probe (WinAPI on Windows); repeat SessionStarts adopt the running daemon instead of respawning it. Stderr (WARNING+) goes to `.memsearch/watch.log`, rotated to `watch.log.1` on restart.
- **Stop**: stop is manual — send SIGTERM/SIGINT to the pid (or `os.kill`) and remove `.watch.pid`. On Windows a headless process has no console for Ctrl-C, so termination is direct (TerminateProcess); remote state is server-side and self-heals.

## Memory Files

`.memsearch/memory/YYYY-MM-DD.md` is the human-readable source of truth (append-only; never rewritten or deleted by the plugin):

```markdown
## Session 22:45

### 22:45
<!-- session:05b911c7-... turn:7d15e0e6-... transcript:C:\...\....jsonl -->
- User asked about ...
- WorkBuddy recommended ...
```

## Configuration

| Setting | Where | Notes |
|---|---|---|
| `embedding.*` | global `~/.memsearch/config.toml` | e.g. openai/dashscope text-embedding-v4 |
| `[llm.providers.<name>]` | global | provider used by summarize |
| `plugins.openclaw.summarize.*` | global | WorkBuddy reuses the openclaw slot |
| `milvus.uri` | global | Milvus Lite file or Zilliz Cloud endpoint |
| project allowlist | `<project>/.memsearch.toml` | only 7 keys (e.g. `milvus.collection`) |

Environment variables:

| Variable | Default | Effect |
|---|---|---|
| `MEMSEARCH_DISABLE` | — | `1` makes every hook return `{"continue": true}` (recursion guard for maintenance chains) |
| `MEMSEARCH_WB_LAG_WINDOW` | `1200` | Lag-hint window in seconds |
| `MEMSEARCH_WB_WATCH` | — | `1` starts the watch daemon on SessionStart (server mode only; Lite falls back to one-shot index) |
| `MEMSEARCH_NO_WATCH` | — | Set to `1` in all child processes spawned by the plugin |
| `HOOK_REVIEW_DIR` | `<project>/.hook-review/` | Output dir for the dev capture tool below |

## Development Tools: Payload Capture & Schema

`scripts/review_capture.py` is a standalone, stdlib-only dev tool (not wired by default). Point hooks at it manually — see `hooks/hooks.review-example.json` — to capture real hook payloads from WorkBuddy or **any other agent framework** when developing new plugins:

- `captures/<event>.jsonl` — sanitized raw payloads (strings > 500 chars, arrays > 50 items, depth > 8 truncated)
- `hook-schema.json` — per-event JSON Schema inferred from all observations: `type` per field (unions as arrays), `x-present` counts, `required` = present in every observation, `x-examples` for scalars, recursive `properties`/`items`

It always responds `{"continue": true}` and never blocks the session.

## Data Governance

The plugin writes these inside a project's `.memsearch/`: appended `memory/*.md`, `.last-index-completed`, `.index.pid`, and — when the watch daemon is enabled — `.watch.pid` + `watch.log(.1)` (all self-managed). The maintenance child additionally coordinates via `.maintenance.pid` (self-managed) while the backend engine owns `.maintenance-state.json`, `.maintenance-openclaw-*.lock`, `skill-candidates/`, and the `PROJECT.md`/`USER.md` outputs. It never touches backend-owned index internals (`.index-state.json`, locks) and never produces intermediate conversion artifacts.

## Repository Layout

```text
.codebuddy-plugin/plugin.json   # WorkBuddy plugin manifest
hooks/hooks.json                # event → scripts/handler.py wiring (production)
hooks/hooks.review-example.json # manual capture wiring (dev only)
scripts/handler.py              # dispatcher + backend calls + watch lifecycle
scripts/parse.py                # transcript last-turn extraction
scripts/review_capture.py       # payload capture + JSON Schema tool
scripts/tests/                  # pytest suite (process mgmt + wiring)
```
