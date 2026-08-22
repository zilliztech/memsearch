# memsearch Hermes plugin

Semantic memory for [Hermes Agent](https://hermes-agent.nousresearch.com) —
MCP tools for recall (the same model as the Zed extension) + a launchd/cron
poller of Hermes's own session store (`~/.hermes/state.db`) for capture.

```
plugins/hermes/
├── install.sh                 # scripts + MCP venv + register instructions
├── README.md
├── server/
│   └── memsearch_mcp_server.py  # the MCP server (state.db capture/transcript)
├── scripts/
│   ├── hermes-capture.py      # state.db poller -> daily .md + index
│   ├── parse-transcript.py    # read original turns from ~/.hermes/state.db
│   └── derive-collection.sh   # per-project Milvus collection name
└── prompts/                   # shared summarize / project_review / user_profile prompts
```

Docs: `docs/platforms/hermes/` (index, how-it-works, memory-tools, installation).

## Install

```bash
bash plugins/hermes/install.sh "$(pwd)"
hermes mcp add memsearch --command "$(pwd)/plugins/hermes/.venv/bin/python $(pwd)/plugins/hermes/server/memsearch_mcp_server.py"
```

Then ask Hermes: *"recall what we decided about X"* — it calls `memory_search`.

## Architecture

- **Recall** — the MCP server exposes `memory_search`, `memory_get`,
  `memory_transcript`, `memory_capture` as first-class Hermes tools (Hermes
  has a built-in MCP client).
- **Capture** — `hermes-capture.py` polls `~/.hermes/state.db` and appends
  turns to `<home>/.memsearch/memory/YYYY-MM-DD.md` in the shared format,
  then re-indexes. Runs as a launchd daemon (2m poll) or a cron.
- **Memory home** — conversations live in a dedicated folder (default
  `~/hermes`, override `HERMES_MEMORY_HOME`) so Hermes logs don't pollute
  project repos.
