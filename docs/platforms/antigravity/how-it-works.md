# How it works

## Capture and indexing

Antigravity's `Stop` hook supplies the conversation ID, working directory,
workspace paths, completion state, and transcript path. The plugin snapshots
the completed turn and hands it to a detached worker. Model calls and database
work run after the hook returns.

The worker generates a short summary, appends it to the daily Markdown journal,
and indexes the journal with MemSearch. Each entry retains its source session,
turn, and transcript anchor. Replay protection keeps repeated callbacks from
creating duplicate journal entries.

The native summary helper runs with a dedicated agent configuration and
Hydrogen Low. It receives the supplied text with inherited hooks and external
tools disabled. User-facing conversation text is summarized; original tool
calls and outputs remain available through transcript recall.

Pending capture jobs and index status are stored locally. Jobs run in turn
order, and a new session resumes unfinished work. A successful Markdown write
survives an indexing failure; retrying that job rebuilds its index without
generating the summary again.

Antigravity clients coordinate access to a local Lite database, including when
several workspaces share its URI. Server and Unix-socket connections use their
normal concurrent client access. Database clients and local access locks are
released before maintenance model calls begin.

## On-demand recall

At startup, the plugin supplies a short capability hint and available durable
project/user notes. It leaves search to the agent's `memory-recall` skill:

| Layer | Action | Result |
|-------|--------|--------|
| L1 | Search the project's collection | Relevant snippets and source locations |
| L2 | Expand a selected result | The surrounding Markdown section and anchor |
| L3 | Read the anchored transcript | Original user/assistant turns and tool calls |

The plugin's CLI adapter carries the project scope and ONNX defaults into
`memsearch search`, `expand`, and `transcript`. Explicit user configuration keeps
its normal precedence. The original Antigravity JSONL is parsed by the shared
`memsearch transcript` command, so other agents can also follow these anchors.

## Optional maintenance

The adapter calls the shared maintenance runner for project review, user
profiling, and skill distillation. Tasks use the existing per-task locks, due
state, input digests, prompt templates, and output validation. Native model
execution is the Antigravity-specific part; named API providers use the shared
provider implementation.

Native maintenance can request up to three read-only expansions or transcript
excerpts before producing its final result. The adapter uses the shared command
validator, preserves the project collection, and limits transcript reads to
anchors supplied in the journals. Skill candidates can therefore retain exact
workflow commands and flags from the original conversation. Candidates enter
the shared Git-backed store for review and explicit installation.

See [installation and configuration](installation.md) to enable these tasks.
