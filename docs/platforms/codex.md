# Codex CLI Plugin

**Semantic memory for [Codex CLI](https://github.com/openai/codex).** Shell hooks and a memory-recall skill, similar in architecture to the Claude Code plugin.

---

## Quick Start

### Prerequisites

- Codex CLI v0.116.0+
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

### Installation

```bash
# 1. Clone the memsearch repo (if not already)
git clone https://github.com/zilliztech/memsearch.git

# 2. Run the installer
bash memsearch/plugins/codex/scripts/install.sh
```

The installer:

1. Copies the memory-recall skill to `~/.agents/skills/`
2. Generates `~/.codex/hooks.json` with memsearch hooks
3. Enables `codex_hooks = true` in `~/.codex/config.toml`
4. Makes all scripts executable

### Usage

```bash
codex --yolo
```

!!! warning "Why `--yolo`?"
    Codex needs `--yolo` mode on the first run because the ONNX embedding model downloads from HuggingFace Hub (network access required). After the model is cached, `--yolo` is still needed because hooks execute shell commands.

### Pre-cache the Model (optional)

```bash
memsearch search "test" --collection test_warmup --provider onnx 2>/dev/null || true
```

---

## What Happens Automatically

| Event | What memsearch does |
|-------|-------------------|
| **Session starts** | Cleanup orphaned processes, start watch, inject recent memories |
| **Each prompt** | Memory-recall skill hint displayed |
| **Each turn ends** | Conversation summarized via `codex exec` and saved to daily `.md` |

---

## Capture

The Stop hook runs **asynchronously** after each Codex response:

1. Parses the last turn from the Codex rollout JSONL using `parse-rollout.sh`
2. Summarizes via `codex exec` with an isolated `CODEX_HOME` (prevents hook recursion)
3. Uses `gpt-5.1-codex-mini` for summarization (with a fallback to local truncation if `codex exec` fails)
4. Appends summary with `<!-- session:ID rollout:PATH -->` anchor to `.memsearch/memory/YYYY-MM-DD.md`
5. Re-indexes immediately (Server mode only; Lite mode skips due to file lock)

!!! note "No SessionEnd hook"
    Codex CLI does not have a `SessionEnd` hook. Orphaned watch processes are cleaned up at the next `SessionStart`.

---

## Memory Recall

The `$memory-recall` skill provides semantic search over past sessions. Invoke it:

- **Automatically**: Codex decides when past context would help
- **Manually**: `$memory-recall <your query>`

### Three-Layer Progressive Disclosure

| Layer | Command | What it returns |
|-------|---------|----------------|
| **L1: Search** | `memsearch search` | Top-K relevant chunk snippets |
| **L2: Expand** | `memsearch expand` (or direct file read as fallback) | Full markdown section |
| **L3: Transcript** | `bash parse-rollout.sh <rollout_path>` | Original Codex conversation |

!!! note
    Codex does not support `context: fork` for skills. The skill runs in the main context. As a fallback for L2, the skill can read source files directly using `cat` with line ranges if `memsearch expand` fails due to sandbox restrictions.

---

## Memory Files

```
your-project/.memsearch/memory/
├── 2026-03-24.md
└── 2026-03-25.md
```

Example:

```markdown
# 2026-03-25

## Session 10:30

### 10:30
<!-- session:abc123 rollout:~/.codex/sessions/abc123.rollout.jsonl -->
- User asked about database migration strategy
- Codex implemented Alembic migration for new user_preferences table
- Added rollback script and tested migration on staging
```

---

## Configuration

### Embedding Provider

Default: `onnx` (bge-m3, CPU, no API key). Change with:

```bash
memsearch config set embedding.provider openai
export OPENAI_API_KEY="sk-..."
```

### Milvus Backend

Default: Milvus Lite (`~/.memsearch/milvus.db`). For remote Milvus:

```bash
memsearch config set milvus.uri http://localhost:19530
```

---

## Uninstall

```bash
# Remove hooks
rm ~/.codex/hooks.json

# Remove skill
rm -rf ~/.agents/skills/memory-recall

# Disable hooks in config
# Edit ~/.codex/config.toml and set codex_hooks = false

# Optionally remove memsearch
uv tool uninstall memsearch
```

---

## Updating

```bash
# Update memsearch
uv tool upgrade memsearch

# Re-run installer to update hooks and skill
bash memsearch/plugins/codex/scripts/install.sh
```

---

## Plugin Files

```
plugins/codex/
├── hooks/
│   ├── common.sh                   # Shared setup (with orphan cleanup)
│   ├── session-start.sh            # SessionStart hook
│   ├── stop.sh                     # Stop hook (async, codex exec)
│   └── user-prompt-submit.sh       # UserPromptSubmit hint
├── skills/
│   └── memory-recall/
│       └── SKILL.md                # Memory recall skill
└── scripts/
    ├── derive-collection.sh        # Per-project collection name
    ├── install.sh                  # One-click installer
    └── parse-rollout.sh            # Codex rollout JSONL parser
```
