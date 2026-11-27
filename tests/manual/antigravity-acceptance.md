# Antigravity acceptance — 2026-11-27

This records development-source acceptance on Linux with Antigravity CLI
1.5.18 and plugin 0.1.0. Chat and summary calls used the authenticated native
`gemini-4-hydrogen-low` model; embeddings used real local ONNX. The Python core
and plugin came from the same feature checkout. No model responses were mocked
in the native scenarios below.

See [the manual procedure](antigravity.md) and
[the TUI harness](antigravity_e2e.py) to repeat these checks. Projects, database
files, collections, configuration, and target tmux sessions were isolated.

## Online native TUI

Each backend had a real writer and a fresh reader. Readers received the project
marker and questions, without the expected answers. Evidence includes actual
skill loading, search/expand/transcript commands, tool results, journal anchors,
and final responses.

| Backend | Dependency stack | Verified behavior |
|---|---|---|
| Lite 2 local file | milvus-lite 2.5.1, pymilvus 2.6.8, ONNX Runtime 1.24.3 | Four writer turns; correction from 43 to 67 seconds; `紫羽-λ`; repeated workflow; L3-only `L3-VIOLET-8264` recovered |
| Lite 3 local directory | milvus-lite 3.2.2, pymilvus 3.0.3, ONNX Runtime 1.32.0 | Two writer turns; 83 minutes, coral, `火羽-Σ`; L3-only `L3-EMBER-3728` recovered |
| Authenticated Server | disposable milvusdb/milvus:v3.0.5, HTTP/TCP | Correction from 64 to 79 seconds; `铜羽-β`; L3-only `L3-COPPER-9571`; concurrent recall and rapid writer turns |
| Separate Lite 2 server | Unix socket, pymilvus 2.6.8 | Fresh writer/reader recovered green, 91 seconds, `玉羽-Ω`, and the original anchored exchange |

The tool-only probes were absent from the initial writer summaries and
present in original transcript output. Readers followed those anchors to
recover them. Runtime interpreter traces confirmed the intended Lite 2 and
Lite 3 dependency stacks.

Server queries also observed growing rows before explicit flush: two rows
were readable while the collection statistics still reported zero.

A separate project returned no foreign facts under its derived collection.
After explicitly configuring the shared collection, its native reader recovered
the expected Server memory. With capture disabled, that project wrote no
journal entries.

Some reader commands contained a mistyped long project path; the native reader
corrected the path and completed recall. The failed calls remain in the test
evidence alongside successful calls.

## Recovery

| Trigger | Evidence and result |
|---|---|
| Rapid consecutive turns | Second native turn arrived while the first job was pending; both were written and indexed once in order |
| Repeated Stop | Replayed a real observed payload; journal hash, entry count, and summary attempts stayed unchanged |
| Invalid summary model | Real TUI turn stayed pending, with no fallback/error text in Markdown; corrected private config plus a new native SessionStart recovered it |
| Worker interruption | Terminated the exact owned worker and native children; a new native SessionStart resumed the pending job and released the lock |
| Server outage | Stopped the disposable Server during a real TUI turn; Markdown remained intact and index status recorded the error; restart plus native SessionStart indexed it with the summary attempt count still one |
| Empty/cancelled/error Stop | Synthetic mutations of observed hook payloads produced no journal entries; this check does not claim an interactive UI cancellation test |

Online acceptance covered 26 indexed turns across four certified projects,
plus two disabled-capture turns. Early harness preflight runs are excluded
from those counts.

## Automatic native maintenance

With the three tasks enabled in a private configuration, an ordinary TUI
`Stop` triggered project review, user profiling, and skill distillation.
Project review retained the corrected 67-second retry and the release policy;
user profiling retained the synthetic preferences for concise reports and
exact Unicode labels.

Skill distillation produced `release-rehearsal` from three occurrences. Its
native helper requested an anchored transcript through the bounded read-only
bridge and recovered these exact commands:

```bash
python3 workflow.py inspect --profile violetsafe
python3 workflow.py verify --strict
```

The flags were absent from the journal input used for this run. The input
digest matched the saved journal prefix, and an independent transcript replay
matched the bridge output hash and contained both flags. The native TUI then
reviewed and installed the candidate. A fresh session read the installed
`SKILL.md` and successfully executed both commands.

A further TUI turn changed the private rehearsal procedure. Its ordinary Stop
updated the existing candidate and created a real candidate-store Git commit
(`distill: evolve 1 candidate skill(s) [antigravity]`). The installed skill
retained its prior contents until explicit review and reinstallation.
Reinstallation created the corresponding `install` commit and copied the
updated candidate exactly, clearing its pending-update status.

Subsequent ordinary Stop events exercised unchanged-input and 24-hour interval
skips. Durable notes, task state, and native-read audit files stayed unchanged.

## Additional integration checks

- A real native writer and fresh reader completed search, expansion, and
  transcript recall with spaces in both project and plugin paths.
- The interactive `memsearch config init` ran under a PTY and saved the summary
  settings and all three native maintenance tasks to a private configuration.
- Separate real index and recall processes shared one Lite URI across different
  projects. A controlled gate held the indexing client open; traces confirmed
  that recall waited for the same lock and proceeded after release. Lite 2 and
  Lite 3 both passed this check, bounded busy-error handling, and retry. This
  checks actual database processes with an instrumented delay.

The full Python regression run passed **923 tests**, with **17 skipped**.
After the final configuration-wizard refinement, all **13 configuration-helper
tests** passed, including the added named-provider model-fallback regression.
Ruff lint and format checks, shared bundle synchronization, `git diff --check`,
and the strict MkDocs build passed.

## Installation and deferred coverage

The actual `agy plugin install` command succeeded in a fresh private HOME.
The installed plugin was enabled, with three skills, one helper agent, and one
hook group. Strict native validation passed and installed files matched the
source bundle (29 files). This is source-install verification, separate from a published
release acceptance run.

Zilliz Cloud acceptance is deferred by agreement because the available test
endpoint could not be reached. Desktop, macOS, and Windows interfaces were
not exercised on this Linux host.
