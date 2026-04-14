# Troubleshooting

Common issues when using the memsearch OpenCode plugin.

---

## The plugin is installed but no memory files appear

### Checks

- Confirm the plugin is enabled in your OpenCode config
- Verify `.memsearch/memory/` exists in the project root after a few turns
- Make sure the project directory is writable

### Why this happens

The OpenCode plugin relies on a background capture daemon that polls OpenCode's SQLite database. If the daemon never starts, or the project directory is not writable, no markdown memory files will appear.

---

## The capture daemon stops unexpectedly

### Symptoms

- Memory capture worked before, then stopped
- `.memsearch/.capture.pid` exists but no new memories are being written

### Checks

- Remove stale PID files if the daemon is no longer running
- Re-run OpenCode so the plugin can auto-start the daemon again
- Check whether a previous daemon crashed due to local environment issues

### Why this happens

The plugin uses a PID file singleton to avoid running multiple capture daemons per project. If the daemon crashes without cleaning up, the stale PID file can block restart until it is removed.

---

## Recall is weak or returns incomplete history

### Checks

1. Confirm memory files exist:

```bash
ls .memsearch/memory/
```

2. Rebuild the index if files were imported or edited manually:

```bash
memsearch index .memsearch/memory
```

3. Confirm your embedding backend is configured as expected:

```bash
memsearch config get embedding.provider
```

### Why this happens

memsearch treats markdown as the source of truth and Milvus as a rebuildable index. If the markdown changed without re-indexing, or embeddings are misconfigured, retrieval quality will drop.

---

## Summarization subprocess behaves strangely

### Symptoms

- Summaries fail or loop unexpectedly
- The plugin seems to trigger itself recursively

### Why this happens

The plugin isolates summarization by launching `opencode run` with a separate `XDG_CONFIG_HOME` and additional guards. If your local configuration or shell environment overrides those assumptions, the summarization subprocess can behave differently than expected.

### What to check

- Compare your normal OpenCode config with the isolated summarization environment
- Verify custom shell startup scripts are not injecting conflicting environment variables
- Re-test with a minimal local configuration

---

## Cold-start memory is missing from a new session

### Checks

- Confirm recent `.memsearch/memory/*.md` files exist
- Start a fresh OpenCode session after memory has already been captured
- Verify the plugin still loads `experimental.chat.system.transform`

### Why this happens

Recent-memory injection happens at session start. If no recent memory exists yet, or the plugin did not load correctly for that session, there may be nothing to inject into the system prompt.
