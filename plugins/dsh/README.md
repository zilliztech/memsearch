# @zilliz/memsearch-dsh

MemSearch plugin for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH).
It gives DSH persistent, cross-agent memory on the same `.memsearch/memory/`
markdown store used by the Claude Code, Codex, OpenClaw, and OpenCode plugins,
backed by a Milvus hybrid search index.

```
capture  ── session/event turn/end ──> summarize (dsh-headless agent default, or custom-llm) ──> memory/YYYY-MM-DD.md
inject   ── agent/pre-step step 1  ──> memsearch search ──> relevant chunks injected (zero cost otherwise)
recall   ── ctx.skills.register(memory-recall) ──> search → expand → transcript
```

## Prerequisites

- Install memsearch:

  ```bash
  uv tool install "memsearch[onnx]"
  ```

- A DSH profile (web / headless / tui) you want to attach memory to.
- Node >= 22.19 (DSH's requirement).

## Install

### From npm (recommended, once published)

```bash
dsh plugin --profile web add @zilliz/memsearch-dsh
```

### From source (development)

```bash
dsh plugin --profile web add /path/to/memsearch/plugins/dsh
```

> `dsh plugin` is a pnpm forwarder: it links the package into the profile,
> detects the `dsh.bundle` declaration in `package.json`, and appends it to
> the profile's bundle layers. `cordis.patch.yml` inside the package then
> inserts the `memsearch` row into the profile's plugin tree.
>
> Replace `web` with your profile name (`headless`, `tui`, ...), and restart
> DSH for the profile (or start a new session) so the plugin mounts.

### Manual patch insertion (no `dsh plugin`)

Append this row to the profile's `cordis.patch.yml` and make sure
`@zilliz/memsearch-dsh` is resolvable from the profile's `node_modules` (for example a
`link:` dependency):

```yaml
- insert:
    - id: memsearch
      name: '@zilliz/memsearch-dsh'
```

### Verify it loaded

Start DSH and check the session log for the plugin mount, or confirm the
`memory-recall` skill is available through the `skill` tool. Captured turns
land in `<project>/.memsearch/memory/YYYY-MM-DD.md`.

## Configuration

The plugin is configured through the profile's `cordis.patch.yml` `config`
block (patch the `memsearch` row you inserted). All keys are optional.

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `captureEnabled` | bool | `true` | Capture completed turns into memory. |
| `injectEnabled` | bool | `true` | Inject relevant memory before each turn's first step. |
| `summarizeEnabled` | bool | `true` | Summarize turns before writing (on failure a short unavailable note is written, never a raw dump). |
| `summarizeMode` | string | `auto` | Summarizer backend. `auto` (default) mirrors the other platform plugins: if `[plugins.dsh.summarize] provider` is set in memsearch config, it uses `custom-llm`; otherwise `dsh-headless` (zero-config DSH agent). Explicit `dsh-headless` / `custom-llm` pin the backend. |

Everything else — provider/model, Milvus, collection, memory dir — comes from
**memsearch config / environment**, exactly like the other platform plugins
(no per-plugin config fields):

- **Summarize provider/model** → `[plugins.dsh.summarize] provider` / `model`
  in `~/.memsearch/config.toml` (or `[llm.providers.*]`; see the
  `custom-llm` section below).
- **Milvus** → `[milvus] uri` in memsearch config.
- **Collection** → derived from the project path (`derive-collection.sh`),
  or `--collection` passed to the memsearch CLI.
- **Memory dir** → `MEMSEARCH_DIR` env (explicit → global scope), else
  `<project>/.memsearch`.

### Maintenance tasks (PROJECT.md / USER.md / skills)

Optional background upkeep, aligned with the other platform plugins. Each task
is disabled by default; enable the ones you want in `~/.memsearch/config.toml`:

```toml
[plugins.dsh.project_review]
enabled = true            # maintain .memsearch/PROJECT.md
[plugins.dsh.user_profile]
enabled = true            # maintain .memsearch/USER.md
[plugins.dsh.memory_to_skill]
enabled = true            # distill recurring workflows into skill candidates
min_occurrences = 3       # how often a workflow must recur before distilling
```

Common settings per task: `provider` (`native` = a one-shot DSH headless
agent, default), `model`, `min_interval_hours` (default 24), `input_dir`,
`output_file`. Candidates land in `.memsearch/skill-candidates/` (git-tracked)
and are **never installed automatically** — installing is a human step (see
the `memory-to-skill` skill in the other platform plugins).

Example override layer (add this to the profile's own `cordis.patch.yml`):

```yaml
- id: memsearch
  config:
    summarizeMode: dsh-headless   # pin the headless backend (default is auto)
```

### Summarization modes

Two backends are available, selected by `summarizeMode` — the same
"configured choice" the Claude Code / Codex / OpenClaw / OpenCode plugins
offer (each can summarize with their own LLM or a headless agent + small
model). The default (`auto`) matches theirs: configure a provider and you get
a direct LLM call; configure nothing and you get a headless agent.

- **`auto`** (default) — mirrors the other platform plugins:
  - if `[plugins.dsh.summarize] provider` is set in memsearch config
    (`~/.memsearch/config.toml`, same place the other plugins read), use
    `custom-llm` with that provider/model;
  - otherwise use `dsh-headless` (zero-config DSH agent).
  This means the plugin behaves like the other four: **configure a provider
  → direct LLM; configure nothing → headless**.
- **`dsh-headless`** — boots a one-shot DSH headless agent
  (`dsh --profile headless "<summarize task>"`) to write the notes, mirroring
  how the other plugins reuse their own agent's headless mode. Zero-config for
  anyone already using DSH: the sub-agent's model is the deployment's
  `agent-default-model` — the user layer of `~/.dsh/settings.yaml` (the same
  selection the Web UI model settings write) wins over any patch, so **the
  `[plugins.dsh.summarize]` provider/model do NOT apply here** — change the
  model in DSH settings (`agent-default-model:` in `~/.dsh/settings.yaml`, or
  the Web UI model picker) instead. The boot is asynchronous and fire-and-forget,
  so the few seconds of headless startup never block the conversation. Requires
  `dsh` on PATH or `DSH_CLI` set to the CLI
  entry. The sub-agent is booted with `MEMSEARCH_DSH_SUMMARIZE=1`; the plugin
  checks that flag and stays inert (no capture / inject / skill) inside the
  summarizer, so the summarizer's own session is never re-captured in a loop.
- **`custom-llm`** — `scripts/summarize.py` imports memsearch's
  `[llm.providers.*]` config and calls the LLM directly. Lightweight: one
  python process, no DSH boot, no extra CLI dependency. Choose this when you
  want a specific small model (e.g. an official `deepseek-v4-flash` key in
  memsearch config) without booting an agent. Provider selection
  (most specific first):
  1. `[plugins.dsh.summarize] provider` (or the `summarizeProvider` CLI
     argument summarize.py receives from it) — looked up in
     `[llm.providers.<name>]`; a missing entry fails loudly (visible error),
     never a silent empty write.
  2. `llm.provider` when it names a configured provider or is a raw type.
  3. `compact.llm_provider` (deprecated) or `openai` as a final default.

There is **no automatic fallback between modes**: the backend you configure
(or auto resolves) is the backend used. If it fails (missing dsh CLI, bad
provider config), a short unavailable note is written with the reason — the
plugin never silently switches to an LLM you did not configure.

A failed summarization writes a short unavailable note (mirroring Claude
Code's behavior — memory stays clean, the transcript anchor keeps the raw
content reachable for progressive disclosure), and logs a visible warning
through the DSH logger.

## How it works

- **Capture** — listens on `session/event` for `turn/end`, renders the turn
  (`[User]` / `[Assistant]` / `[Tool call]` lines), then fire-and-forget
  summarizes (if enabled) and appends it to the **session's own**
  `memory/YYYY-MM-DD.md` with the shared anchor format
  `<!-- session:<id> turn:<N> db:<path> -->`. The project directory comes from
  `session.header.cwd`, so a long-lived web surface captures every project it
  hosts, not just the process's boot directory. Turns are serialized (LLM
  summarize calls never overlap) and `captureExists` dedup keeps each turn
  idempotent if its event replays.
- **Inject** — on `agent/pre-step` at step 1, runs a bounded memsearch search
  over the user's question. Only when relevant chunks exist does it inject
  them plus a `[memsearch] Memory available.` hint; otherwise the decision is
  returned unchanged (zero context cost).
- **Recall** — registers a `memory-recall` skill (invocable through DSH's
  native `skill` tool) that performs search → expand → transcript drill-down
  and returns a curated summary.
- **Maintenance** — runs the shared maintenance runner (PROJECT.md / USER.md
  upkeep and memory-to-skill distillation), triggered on `session/disposed`
  plus a 6-hourly fallback timer. Each task is a due-state machine: it runs at
  most once per `min_interval_hours` (default 24h) and only when enabled in
  memsearch config (`[plugins.dsh.project_review]`, `[plugins.dsh.user_profile]`,
  `[plugins.dsh.memory_to_skill]`), mirroring the other platform plugins. The
  maintenance work is executed by a one-shot DSH headless agent (the same
  `dsh --profile headless` mechanism as summarization), booted with
  `MEMSEARCH_DSH_SUMMARIZE=1` so the plugin stays inert inside it.

## Uninstall

```bash
dsh plugin --profile web rm @zilliz/memsearch-dsh
```

Removing the dependency drops the profile-layer entry; the memory markdown
files and the Milvus index are left untouched.

## Development

- The plugin is plain ESM with no build step — `dsh plugin add` links the
  checkout directly, so edits are live after a profile reload.
- Python helpers under `scripts/` are linted with the repo's `ruff` config and
  tested under `plugins/dsh/tests/`.
- Keep the memory-write format byte-compatible with the other platform
  plugins; see `plugins/opencode/scripts/capture-daemon.py` for the canonical
  writer.
