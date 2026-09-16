# Troubleshooting

Common issues when using the memsearch OpenClaw plugin.

---

## Plugin installed but memory tools do not appear

### Symptoms

- `memory_search` / `memory_get` / `memory_transcript` are missing
- OpenClaw starts normally, but the plugin looks inactive

### Checks

1. Confirm memsearch itself is installed:

```bash
memsearch --help
```

2. Confirm the plugin is installed:

```bash
openclaw plugins list
```

3. Restart the gateway after installation or config changes:

```bash
openclaw gateway restart
```

### Why this happens

The plugin is loaded by the OpenClaw gateway. Installing the package without restarting the gateway can leave the old plugin state in memory.

---

## Conversations are not being captured into `.memsearch/memory/`

### Symptoms

- The plugin loads, but no daily markdown files appear
- Recall tools return little or no history after several conversations

### Checks

For the main agent workspace:

```bash
ls ~/.openclaw/workspace/.memsearch/memory/
```

For a custom agent, check that agent's workspace instead.

### Things to verify

- `autoCapture` is enabled in `openclaw plugins config memsearch`
- You have completed at least one normal conversation turn
- The OpenClaw workspace is writable

### Why this happens

The plugin captures memory from OpenClaw lifecycle hooks and writes summaries into the current agent workspace. If you are checking the wrong workspace, or capture is disabled, the files will appear to be missing.

---

## Recall is weak or returns the wrong memories

### Symptoms

- Relevant memories are missing from results
- Keyword-heavy queries do not show the expected entries

### Checks

1. Make sure memory files actually exist:

```bash
find ~/.openclaw -path '*/.memsearch/memory/*.md' | head
```

2. Rebuild the index if you imported or edited markdown files manually:

```bash
memsearch index ~/.openclaw/workspace/.memsearch/memory
```

3. Confirm your embedding backend is configured correctly:

```bash
memsearch config get embedding.provider
```

### Why this happens

memsearch stores memories as markdown and indexes them into Milvus. If the markdown changed without re-indexing, or the embedding backend is misconfigured, retrieval quality will degrade.

---

## The plugin is using the wrong memory set for a different agent

### Symptoms

- `main` and `work` seem to share context unexpectedly
- A custom agent cannot find memories you expected

### Why this happens

memsearch isolates OpenClaw memory by **workspace directory**, not by agent name alone. Different agents only share memory when they point to the same workspace path.

### Fix

Check the workspace configured for each agent and make sure it matches your intended isolation model.

If you want separate memories, use separate workspaces.
If you want shared memories across platforms, point the agent workspace at the same project directory used elsewhere.

---

## Cold-start memory injection does not show recent context

### Symptoms

- A new session starts without visible recent-memory context
- The agent seems unaware of recent work until tools are called manually

### Checks

- Ensure `autoRecall` is enabled in plugin config
- Verify recent memory files contain bullet-point entries
- Start a fresh agent session after enabling the plugin

### Why this happens

The plugin injects recent context during `before_agent_start`. It reads recent daily logs and extracts concise bullet-point memory lines. If there is no recent captured memory yet, there may be little to inject.

---

## Install from source works, but local changes do not seem to apply

### Symptoms

- You edited `plugins/openclaw/`, but behavior did not change

### Fix

Reinstall the local plugin path and restart the gateway:

```bash
openclaw plugins install ./plugins/openclaw
openclaw gateway restart
```

### Why this happens

The gateway loads the installed plugin, not your editor buffer. Local file changes only take effect after reinstall/reload.

---

## Still stuck?

- Review the [Installation](installation.md) guide
- Review [How It Works](how-it-works.md) to understand capture and recall behavior
- Open an issue on GitHub with your OpenClaw version, OS, and reproduction steps
