# Antigravity native acceptance

`antigravity_e2e.py` drives an actual Antigravity TUI in task-owned tmux
sessions. It uses the source plugin and Python core, real native Hydrogen Low
responses, and real ONNX embeddings. Run it manually on Linux; it is outside
the ordinary CI suite.

## Prerequisites

- An installed, authenticated `agy` with access to `gemini-4-hydrogen-low`.
- `tmux`, `bwrap`, and a system permitting an unprivileged mount namespace.
- A MemSearch development environment with the ONNX extra and a cached model.
- A fresh evidence directory and disposable database or server collection.

The harness redirects MemSearch configuration to a private TOML file. A mount
namespace keeps Antigravity's mutable settings, first-run state, and synthetic
transcripts in the evidence directory while retaining the existing login.
Credential contents are never copied into artifacts. Test plugin directories
are actual copies with recorded source hashes.

The private Python launchers exec the selected environment's original Python
path so its virtual environment is preserved. The isolation shim restores the
private `memsearch` wrapper at the front of PATH after host login-shell setup.
`evidence/interpreters.jsonl` records the actual core and interpreter used by
hooks, workers, and CLI calls. Check these records against `environment.json`;
preparation metadata alone does not prove which dependency stack ran.

`prepare` accepts `--source CHECKOUT`, `--python PYTHON`, `--agy EXECUTABLE`,
`--native-model MODEL`, and `--embedding-provider PROVIDER`. Defaults use this
checkout, the `agy` found on PATH, native Hydrogen Low, and cached ONNX.
Candidate distillation and installation initialize and commit to the private
candidate-store Git repository normally. Verify its log alongside candidate
metadata and installed content. These runtime commits are separate from the
source repository.

## Start a writer

From the repository checkout:

```bash
export AGY_E2E_ROOT="$(mktemp -d /tmp/memsearch-agy-e2e.XXXXXX)"
uv run python tests/manual/antigravity_e2e.py prepare \
  --root "$AGY_E2E_ROOT" --project example
uv run python tests/manual/antigravity_e2e.py start \
  --root "$AGY_E2E_ROOT" --project example --session writer
uv run python tests/manual/antigravity_e2e.py screen \
  --root "$AGY_E2E_ROOT" --session writer --label startup
```

Read the screen before sending input. Use `keys --key Enter` (or another
explicit key) for a visible setup or permission prompt. The helper leaves
those decisions to the operator. Send a substantive prompt with:

```bash
uv run python tests/manual/antigravity_e2e.py send \
  --root "$AGY_E2E_ROOT" --session writer \
  --text 'Synthetic project ORCHID: retry after 47 seconds; rollback label cedar. Confirm these decisions.'
```

Wait for the reply and background capture. Inspect the project's
`.memsearch/memory/`, `.memsearch/.antigravity/jobs/`, and `.index-state.json`.
Send several turns: correct a decision, add Unicode text, and execute a small
read-only workflow whose tool output contains a separate synthetic marker.
Keep that marker out of the final spoken answer to exercise L3 recall.

## Start a fresh reader

Use the same project with a new session name:

```bash
uv run python tests/manual/antigravity_e2e.py start \
  --root "$AGY_E2E_ROOT" --project example --session reader
uv run python tests/manual/antigravity_e2e.py screen \
  --root "$AGY_E2E_ROOT" --session reader --label startup
```

After the reader is ready:

```bash
uv run python tests/manual/antigravity_e2e.py send \
  --root "$AGY_E2E_ROOT" --session reader \
  --text 'Use memory-recall to recover the current ORCHID decisions and the original workflow output. Cite the writer anchors.'
uv run python tests/manual/antigravity_e2e.py collect \
  --root "$AGY_E2E_ROOT" --project example
```

Verify the reader actually loads the skill and calls search, expand, and
transcript. Check its answers against the writer's journal and original tool
output, with no answers supplied in the reader prompt. `collect` records
parsed conversation turns and tool calls, source bundle hashes, job states,
and journals. It omits internal reasoning.

Save `writer-journals.json` and `writer-jobs.json` copies before running the
reader. A reader's spoken answer can legitimately add the raw probe to its
own summary. Use the writer-only snapshot to prove the probe originally
required L3. Use `inspect --project example --label writer` to save actual
backend rows. Inspection loads the collection and queries with Strong
consistency, without flushing it.

## Backend and recovery coverage

- Use a separate project for each dependency stack. `prepare --python PATH`
  selects the Python environment; its imported core must still come from this
  checkout. Record `milvus-lite`, `pymilvus`, and ONNX versions.
- For a disposable local Server, pass `--uri http://127.0.0.1:PORT`
  and `--collection ms_agy_e2e_UNIQUE`. `--server-auth` uses the standard public
  `root:Milvus` credential of a disposable test server.
- Exercise a separate Lite Unix endpoint when testing the Lite 2 client/server
  form. Record direct URI probes separately from TUI acceptance.
- Test foreign project exclusion and explicitly shared collections.
- Replay an actual Stop payload, interrupt an owned worker, and temporarily
  stop the owned test Server. Check replay protection, pending job recovery,
  and indexing recovery without another summary call. Restore the Server.
  `replay-stop --project NAME` saves the observed payload and clearly labels
  the replay as synthetic. Compare job count, summary attempts, journal hash,
  and anchor count before and after. `interrupt-worker --project NAME` checks
  the recorded PID's command and cwd, then kills only that worker and its
  descendants. Trigger recovery with a new TUI session's first prompt.
  On Server restart, recheck `docker port` for the exact owned container:
  dynamically published ports may change. Verify health and update only the
  disposable project's URI before triggering its recovery session.
- Use an invalid model only in the private config; restore Hydrogen Low and
  verify the queued turn is captured once. Check disabled capture separately.
- Enable the three maintenance tasks in the private config after real repeated
  workflows. Let a normal Stop trigger them automatically. Inspect PROJECT.md,
  USER.md, skill candidates, due state, and a second unchanged/interval check.
  Review a candidate before installing it into the test project's skills.
  This is a separate offline acceptance phase; online success does not prove
  native maintenance drill-down or candidate-install behavior.

A test report must distinguish real TUI actions, headless calls, synthetic
hook replay, and deterministic regression tests. Record deferred backends
explicitly.

## Offline and local contention checks

Use two actual writer sessions for a repeated workflow. Put its exact flags
in a read-only plan file and ask the writer to report only stage success.
Verify those flags are absent from the journals before enabling maintenance.
Enable `project_review`, `user_profile`, and `memory_to_skill` only in the
private TOML; set `min_occurrences` to the observed distinct-session count.
Let the next ordinary Stop trigger the tasks. Inspect PROJECT.md, USER.md,
candidate contents and `.antigravity/native-maintenance/*.json`. A successful
transcript request should have a result hash matching independent replay,
and the candidate's exact commands must be supported by that original result.

Save the outputs and maintenance state before testing skips. A normal Stop
with summarization temporarily disabled keeps journal input unchanged; verify
all tasks skip with `input unchanged`. Restore summarization and review/install
the candidate into the private `.agents/skills` using the native TUI. Its next
Stop changes journal input but should skip maintenance within the configured
interval. Compare output and audit hashes to prove no duplicate model calls.

For deterministic Lite contention, configure two private projects with the
same disposable local URI and an explicitly shared collection, then run:

```bash
uv run python tests/manual/antigravity_lite_contention.py \
  --root "$AGY_E2E_ROOT" --project writer-project --peer reader-project \
  --query ORCHID
```

The real index pauses at a test-only gate before closing its actual DB client.
Recall starts in the other process while that client is open, waits on the
per-URI lock, and succeeds after release. The helper also exercises a bounded
busy error followed by indexing recovery. Run it for each supported Lite
dependency stack. This instrumented overlap is separate from native TUI
evidence. Include a project name with spaces in a native writer/reader run to
check the injected command's quoting. Exercise `config init` in a PTY with its
global config path redirected to a private TOML file.

## Cleanup

Stop each exact owned target:

```bash
uv run python tests/manual/antigravity_e2e.py stop \
  --root "$AGY_E2E_ROOT" --session reader
uv run python tests/manual/antigravity_e2e.py stop \
  --root "$AGY_E2E_ROOT" --session writer
```

Allow owned background workers to finish and clean up disposable servers.
Retain the evidence directory for review. Never scan or terminate unrelated
sessions or remove another project's database.

Share only the sanitized project `evidence/` directories and the report.
The private `native-state/` tree contains host-generated internal logs and
passthrough links for the existing login; it is not a publication artifact.
