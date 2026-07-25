# Installation

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **pi** ≥ 0.82.0 | `@earendil-works/pi-coding-agent` |
| **Node.js** ≥ 22.19.0 | Matches pi's own requirement |
| **Python 3** | Used by `transcript.py` and the collection derivation script |
| **memsearch CLI** | Installed automatically via `uvx` on first use if missing |

The plugin resolves the memsearch CLI in this order: `memsearch` on `PATH`, then
`~/.local/bin/uvx`, then `uvx` on `PATH`. To install it explicitly:

```bash
uv tool install "memsearch[onnx]"
```

The `onnx` extra runs the bge-m3 int8 embedding model locally on CPU -- no API
key, no GPU.

---

## Install

```bash
pi install git:github.com/zilliztech/memsearch#plugins/pi
```

From a local checkout:

```bash
pi install /path/to/memsearch/plugins/pi
```

To try it for a single run without installing anything:

```bash
pi -e /path/to/memsearch/plugins/pi
```

!!! warning "User scope vs project scope"
    `pi install` writes to user settings (`~/.pi/agent/settings.json`). Adding
    `-l` writes to project settings (`.pi/settings.json`) instead -- but pi only
    loads project resources **after the project is trusted**, so a project-scoped
    install does nothing until you trust the project in an interactive session.
    Non-interactive runs (`pi -p`) cannot grant trust. Prefer user scope unless
    you specifically want the package shared through a checked-in
    `.pi/settings.json`.

!!! danger "Review before installing"
    pi packages run with full system access: extensions execute arbitrary code
    and skills can instruct the model to run executables. Read the source of any
    third-party package first.

---

## Verify

Start pi in any project and ask what memory tools are available. All three
should be listed:

```
memory_search
memory_get
memory_transcript
```

Then have a short conversation, exit, and check that a journal was written:

```bash
cat .memsearch/memory/$(date +%Y-%m-%d).md
```

A captured turn looks like this:

```markdown
# 2026-07-25

## Session 17:32

### 17:32
<!-- session:019f98… turn:3950049d transcript:/Users/you/.pi/agent/sessions/…jsonl -->
- User asked what a B+ tree is.
- Pi explained that it is a balanced multi-way search tree…
```

Confirm the index picked it up:

```bash
memsearch search "B+ tree" --collection "$(bash plugins/pi/scripts/derive-collection.sh .)"
```

---

## Cross-agent sharing

Nothing needs configuring. Sharing follows from two conventions the plugin
inherits unchanged:

- the collection name is `ms_<dirname>_<sha256-of-abs-path>`, produced by the
  same `derive-collection.sh` every other plugin ships
- journals are written to `<project>/.memsearch/memory/`

Any agent running in the same project directory therefore reads and writes the
same memory. Because the collection is keyed on the **absolute path**, the same
repository cloned to a different path on another machine gets a different
collection; this is existing memsearch behavior, not specific to pi.

---

## Update

```bash
pi update git:github.com/zilliztech/memsearch#plugins/pi
```

For an auto-discovered extension, `/reload` picks up code changes without
restarting. Changes to `pi` settings or package installs require a restart.

Update the CLI separately -- it ships from PyPI:

```bash
uv tool install -U "memsearch[onnx]"
```

---

## Uninstall

```bash
pi remove git:github.com/zilliztech/memsearch#plugins/pi
```

Journals under `.memsearch/memory/` are left alone. They are plain markdown and
remain readable, searchable by other agents, and re-indexable at any time.
