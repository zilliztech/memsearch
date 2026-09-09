# How It Works

## How the Pieces Fit Together

The memsearch Claude Code plugin is a thin integration layer that connects three independent systems:

```mermaid
graph LR
    subgraph "memsearch (Python library)"
        LIB[Core: chunker, embeddings,<br/>vector store, scanner]
    end

    subgraph "memsearch CLI"
        CLI["CLI commands:<br/>search · index · watch<br/>expand · transcript · config"]
    end

    subgraph "plugins/claude-code"
        HOOKS["Shell hooks:<br/>SessionStart · UserPromptSubmit<br/>Stop · SessionEnd"]
        SKILL["Skill:<br/>memory-recall (context: fork)"]
    end

    LIB --> CLI
    CLI --> HOOKS
    CLI --> SKILL
    HOOKS -->|"runs inside"| CC[Claude Code]
    SKILL -->|"subagent"| CC

    style LIB fill:#1a2744,stroke:#6ba3d6,color:#a8b2c1
    style CLI fill:#1a2744,stroke:#e0976b,color:#a8b2c1
    style HOOKS fill:#1a2744,stroke:#7bc67e,color:#a8b2c1
    style CC fill:#2a3a5c,stroke:#c97bdb,color:#a8b2c1
```

The **memsearch Python library** provides the core engine (chunking, embedding, vector storage, search). The **memsearch CLI** wraps the library into shell-friendly commands. The **Claude Code Plugin** ties those CLI commands to Claude Code's hook lifecycle and skill system -- hooks handle session management and memory capture, while the **memory-recall skill** handles intelligent retrieval in a forked subagent context.

This layered design means each piece is independently testable and replaceable. The plugin is just shell scripts and a skill definition -- no compiled code, no background services, no MCP servers.

---

## Hooks

The plugin defines 4 lifecycle hooks that map to Claude Code's session events:

| Hook | Type | Async | Timeout | What It Does |
|------|------|-------|---------|-------------|
| **SessionStart** | command | no | 10s | Start `memsearch watch` for Server or a one-shot index for Lite, inject recent memories as cold-start context, display config and index status |
| **UserPromptSubmit** | command | no | 15s | Return `systemMessage` capability hint "[memsearch] Recall available if needed" (skips prompts < 10 chars) |
| **Stop** | command | **yes** | 120s | Parse and summarize the last turn, lazily create its session heading, append to the daily `.md`; re-index immediately only for Server |
| **SessionEnd** | command | **yes** | 10s | Asynchronously stop any Server watcher and clean up plugin-owned background index processes |

All hooks output JSON to stdout -- `additionalContext` for context injection, `systemMessage` for visible hints, or empty `{}` for no-op. The `common.sh` shared library is sourced by every hook, providing JSON parsing, memsearch binary detection, and watch process management.

### Hook Lifecycle Diagram

This diagram shows how a complete session flows through all four hooks:

```mermaid
stateDiagram-v2
    [*] --> SessionStart
    SessionStart --> Backend
    Backend --> ServerWatcher: Server starts memsearch watch
    Backend --> LiteOneShot: Lite starts one-shot index
    ServerWatcher --> InjectRecent
    LiteOneShot --> InjectRecent

    InjectRecent --> Prompting

    state Prompting {
        [*] --> UserInput
        UserInput --> Hint: UserPromptSubmit hook
        Hint --> ClaudeProcesses: "[memsearch] Recall available if needed"
        ClaudeProcesses --> MemoryRecall: needs context?
        MemoryRecall --> Subagent: memory-recall skill [fork]
        Subagent --> ClaudeResponds: curated summary
        ClaudeProcesses --> ClaudeResponds: no memory needed
        ClaudeResponds --> UserInput: next turn
        ClaudeResponds --> Summary: Stop hook (async)
        Summary --> WriteMD: create heading if needed, then append
        WriteMD --> ServerIndex: Server indexes immediately
        ServerIndex --> UserInput: done
        WriteMD --> UserInput: Lite waits for next SessionStart
    }

    Prompting --> SessionEnd: user exits
    SessionEnd --> StopWatch: async cleanup stops Server watcher
    StopWatch --> StopIndexes: stop plugin-owned indexes
    StopIndexes --> [*]
```

### SessionStart -- Bootstrapping the Session

The SessionStart hook runs once when Claude Code opens a new session. It performs four steps:

1. **Config validation** -- loads resolved config in one snapshot and validates the API key for the configured embedding provider (ONNX needs no key)
2. **Start backend-specific indexing** -- Server launches `memsearch watch .memsearch/memory/` as a singleton background process. Lite cannot share its local database with a watcher, so SessionStart launches one background `memsearch index` attempt instead. A persisted failed or stale index state is included in the visible status before the new attempt starts.
3. **Cold-start injection** -- reads up to 40 lines from each of the 2 most recent daily logs and returns them as `additionalContext` so Claude has immediate awareness of recent work
4. **Update check** -- queries PyPI (2s timeout) and shows an update banner if a newer version exists

SessionStart prepares the memory directory but does not create a daily journal. A journal appears only after the Stop hook captures content.

The cold-start injection is critical for early-session context. Without it, Claude would have no idea what happened yesterday until the memory-recall skill triggers -- but the skill only triggers when Claude judges it would help, which requires knowing that relevant history exists.

### UserPromptSubmit -- The Recall Capability Hint

A lightweight hook that returns a `systemMessage` capability hint: `[memsearch] Recall available if needed`. The hook does not search or imply a match; it keeps Claude aware that the memory system exists, increasing the likelihood that it will invoke the memory-recall skill when a question benefits from historical context.

The hook skips prompts shorter than 10 characters (e.g., "y", "ok") to avoid noise on trivial confirmations.

### Stop -- Capturing the Conversation

The Stop hook is the core of the capture pipeline. It runs **asynchronously** after each Claude response (it does not block the user from sending the next prompt).

```mermaid
graph TD
    A[Stop hook fires] --> B{Recursion guard}
    B -->|"stop_hook_active=true"| Z[Skip]
    B -->|First call| C[Validate transcript file]
    C -->|"< 3 lines"| Z
    C -->|Valid| D["parse-transcript.sh<br/>Extract last turn"]
    D --> E["claude -p --model haiku<br/>Summarize as 3rd-person notes"]
    E --> F["Create session heading if needed<br/>and append with anchors"]
    F --> G{Milvus backend}
    G -->|Server| H["memsearch index<br/>Re-index immediately"]
    G -->|Lite| I["No Stop-time index<br/>Next SessionStart owns indexing"]
```

Step by step:

1. **Recursion guard** -- the hook calls `claude -p` internally (for summarization), which would trigger another Stop hook. The `stop_hook_active` flag prevents infinite recursion. The child process also sets `CLAUDECODE=` to bypass Claude Code's nested session detection, and `MEMSEARCH_NO_WATCH=1` to prevent it from interfering with the main session's watch process.

2. **Transcript validation** -- checks that the transcript JSONL file exists and has >= 3 lines (very short sessions are skipped).

3. **Last-turn extraction** -- `parse-transcript.sh` is a Python 3 script (no `jq` dependency) that extracts the last user question through to EOF. It outputs role-labeled text:
    ```
    [User] How do I fix the N+1 query in order-service?
    [Claude Code] Let me look at the order-service...
    [Claude Code] The issue is in the get_orders function...
    ```

    Raw tool calls, tool outputs, and transient failure details are omitted from summarization input. The assistant's textual response can still mention important files, searches, refactors, findings, and tests, and the summarizer can record those naturally.

4. **Haiku summarization** -- a prompt containing the summary instructions and extracted turn is piped to `claude -p --model haiku`. Set `plugins.claude-code.summarize.model` to override only this native capture model. To use a memsearch-managed API provider instead, define `[llm.providers.<name>]` and set `plugins.claude-code.summarize.provider` to that name. Empty or `native` keeps the Haiku default. The third-person framing ("User asked about...", "Agent implemented...") makes the summaries more useful as memory entries than first-person notes. If the summarizer cannot start, times out, exits unsuccessfully, or returns no text, the hook stores only a short diagnostic marker and retains the transcript anchor for progressive disclosure.

5. **Append with anchors** -- on the first content-bearing Stop for a session, the hook creates the daily file if needed and writes `## Session HH:MM`. Each captured turn is written under a `### HH:MM` heading with an HTML comment anchor. Later Stops in the same session reuse its heading:
    ```markdown
    ## Session 14:30

    ### 14:30
    <!-- session:abc123def turn:ghi789jkl transcript:/home/user/.claude/projects/.../abc123def.jsonl -->
    - User asked about N+1 query performance in order-service
    - Agent identified selectinload as the fix and applied it to get_orders()
    - Added index on order.user_id for the new query pattern
    ```
    These anchors enable the L2→L3 drill-down: `memsearch expand` parses them to surface the transcript path, and the memory-recall skill can then use `memsearch transcript` to read the original conversation.

6. **Backend-specific indexing** -- Server runs `memsearch index` immediately after capture. Lite does not terminate or launch an index from Stop; the next SessionStart one-shot indexes newly captured memory without repeatedly restarting a slow full index.

### SessionEnd -- Cleanup

Runs asynchronously when the session exits. It calls `stop_watch` to terminate the Server `memsearch watch` process and clean up the PID file, then cleans up plugin-owned background index processes, including a Lite one-shot that is still running.

---

## Memory Storage

All memories live in **`.memsearch/memory/`** inside your project directory.

### Directory Structure

```
your-project/
├── .memsearch/
│   ├── .watch.pid            # singleton watcher PID file
│   └── memory/
│       ├── 2026-02-07.md     # daily memory log
│       ├── 2026-02-08.md
│       └── 2026-02-09.md     # today's session summaries
└── ... (your project files)
```

### Example Memory File

A typical daily memory file (`2026-02-09.md`) accumulates all sessions from that day:

```markdown
## Session 14:30

### 14:30
<!-- session:abc123def turn:ghi789jkl transcript:/home/user/.claude/projects/.../abc123def.jsonl -->
- Implemented caching system with Redis L1 and in-process LRU L2
- Fixed N+1 query issue in order-service using selectinload
- Decided to use Prometheus counters for cache hit/miss metrics

### 14:52
<!-- session:abc123def turn:xyz456abc transcript:/home/user/.claude/projects/.../abc123def.jsonl -->
- User asked how to test the cache middleware
- Agent wrote integration tests using fakeredis and pytest fixtures
- Added cache invalidation test covering TTL expiry edge case

## Session 17:45

### 17:45
<!-- session:mno456pqr turn:stu012vwx transcript:/home/user/.claude/projects/.../mno456pqr.jsonl -->
- Debugged React hydration mismatch caused by Date.now() during SSR
- Added comprehensive test suite for the caching middleware
- Reviewed PR #42: approved with minor naming suggestions
```

Each entry is plain markdown -- human-readable, `grep`-able, and git-friendly. The `<!-- session:... -->` HTML comments are invisible when rendered but enable programmatic drill-down.

---

## Markdown Is the Source of Truth

The Milvus vector index is a **derived cache** that can be rebuilt at any time from the markdown files:

```bash
memsearch index .memsearch/memory/
```

This design choice has several important consequences:

- **No data loss.** Even if Milvus is corrupted or deleted, your memories are safe in `.md` files. Rebuild the index and you're back to full functionality.
- **Portable.** Copy `.memsearch/memory/` to another machine, run `memsearch index`, and all your memories are searchable there.
- **Auditable.** You can read, edit, or delete any memory entry with a text editor. Bad summary? Fix it. Sensitive information captured? Delete the line.
- **Git-friendly.** Commit your memory files to version control for a complete project history. Diff, blame, and revert all work naturally.
- **Cross-platform.** Memories written by the Claude Code plugin are searchable from [Codex](../codex/index.md), [DeepSeek Harness](../dsh/index.md), [OpenClaw](../openclaw/index.md), or [OpenCode](../opencode/index.md) -- just point them at the same `.memsearch/memory/` directory.

This contrasts with solutions that store memories in opaque databases (SQLite, ChromaDB, LanceDB). With memsearch, if you can open a text editor, you can read your memories.

---

## Plugin Files

```
plugins/claude-code/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest (name, version, description)
├── hooks/
│   ├── hooks.json               # Hook definitions (4 lifecycle hooks)
│   ├── common.sh                # Shared setup: env, PATH, memsearch detection, watch management
│   ├── session-start.sh         # Start Server watch or Lite one-shot + inject context
│   ├── user-prompt-submit.sh    # Lightweight systemMessage hint
│   ├── stop.sh                  # Parse transcript -> summarize -> lazily create heading -> append
│   ├── parse-transcript.sh      # Deterministic JSONL-to-text parser
│   └── session-end.sh           # Async watcher and owned-index cleanup
├── scripts/
│   └── derive-collection.sh     # Derive per-project collection name from project path
├── skills/
│   └── memory-recall/
│       └── SKILL.md             # Memory retrieval skill (context: fork subagent)
└── transcript.py                # JSONL parser for Claude Code conversations (L3 deep drill via core `memsearch transcript`)
```

| File | Purpose |
|------|---------|
| `plugin.json` | Claude Code plugin manifest. Declares the plugin name (`memsearch`), version, and description. |
| `hooks.json` | Defines the 4 lifecycle hooks with their types, timeouts, and async flags. |
| `common.sh` | Shared shell library sourced by all hooks. Handles stdin JSON parsing, PATH setup, memsearch binary detection (prefers PATH, falls back to `uv run`), memory directory management, and the watch singleton (start/stop with PID file and orphan cleanup). Changes here affect all hooks. |
| `session-start.sh` | Starts the Server watcher or Lite one-shot index, reports persisted index health, reads recent memory files for cold-start injection, and checks for updates. |
| `user-prompt-submit.sh` | Returns lightweight `systemMessage` hint. No search -- retrieval is handled by the memory-recall skill. |
| `stop.sh` | Extracts and validates the transcript, calls `parse-transcript.sh`, summarizes via native Haiku by default or a configured API provider, creates the session heading on the first captured turn, and appends with anchors. Server indexes immediately; Lite defers indexing to the next SessionStart. Has recursion guard (`stop_hook_active`) and sets `CLAUDECODE=` / `MEMSEARCH_NO_WATCH=1` on child processes. |
| `parse-transcript.sh` | Standalone last-turn extractor using Python 3. Outputs role-labeled text. No `jq` dependency. |
| `session-end.sh` | Asynchronously stops the Server watcher and cleans up plugin-owned background index processes. |
| `derive-collection.sh` | Generates a deterministic per-project Milvus collection name from the project path (e.g., `ms_myproject_a1b2c3`). |
| `SKILL.md` | The memory-recall skill definition. Uses `context: fork` to run in an isolated subagent and leaves `model` unset. See [model selection](memory-recall.md#which-model-runs-the-skill). |
| `transcript.py` | Python JSONL parser for Claude Code conversations. Plugin-specific (not in core library); exercised by `tests/test_transcript.py`. The `memory-recall` skill's L3 drill-down uses the core `memsearch transcript` CLI (which auto-detects the format) rather than calling this file directly. |
