# Installation

## Prerequisites

- memsearch CLI installed (`uv tool install "memsearch[onnx]"`).
- Hermes Agent installed (`~/.hermes/state.db` exists after first run).
- Python 3.10+.

## Install

```bash
cd <project-root>
plugins/hermes/install.sh "$(pwd)"
```

That will:

1. Copy `scripts/{hermes-capture.py, parse-transcript.py, derive-collection.sh}` → `<project>/.memsearch/scripts/`.
2. Create the MCP venv (`plugins/hermes/.venv` + `fastmcp`).
3. Print the `hermes mcp add` + capture registration commands.

## Register the MCP server (recall)

```bash
hermes mcp add memsearch --command "<plugin>/.venv/bin/python <plugin>/server/memsearch_mcp_server.py"
```

The agent then has `memory_search` / `memory_get` / `memory_transcript` / `memory_capture` as tools.

## Configure

The memory home defaults to `~/hermes` (dedicated folder — Hermes logs don't
pollute project repos). Override with the `HERMES_MEMORY_HOME` env var. The
server reads Hermes's session store directly, so no extra API keys beyond the
memsearch embedding setup. Optional per-agent config in
`~/.memsearch/config.toml`:

```toml
[plugins.hermes.summarize]
enabled = true
provider = "openai"
model = "deepseek-flash"
```

## Capture

**Continuous (recommended)** — launchd daemon polling `~/.hermes/state.db`
every 2 minutes, with a periodic re-index every 2h:

```bash
launchctl bootstrap gui/$(id -u) <plugin>/hermes-capture-daemon.plist
```

**Or cron** — a recurring job (every 60m):
```
Run: /usr/local/bin/python3 <project>/.memsearch/scripts/hermes-capture.py <project> 60
```

## Verify

```bash
COLL=$(bash .memsearch/scripts/derive-collection.sh "$(pwd)")
memsearch stats --collection "$COLL"
```

Then ask Hermes: *"recall what we worked on recently"* — it calls `memory_search`.