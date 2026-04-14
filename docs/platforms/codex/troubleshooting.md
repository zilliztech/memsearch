# Troubleshooting

Common issues when using the memsearch Codex CLI plugin.

---

## Stop hook does not seem to capture anything

### Checks

- Confirm the plugin was installed with `plugins/codex/scripts/install.sh`
- Verify Codex is actually running with hooks enabled
- Check that `.memsearch/memory/` exists in the project root after a few turns

### Why this happens

Codex capture depends on hook execution plus the summarization command. If hooks are not installed, or the hook command cannot run, no memory file will be written.

---

## Strict sandbox mode blocks summarization

### Symptoms

- The Stop hook runs, but summarization fails
- You see permission-related errors around Codex sandboxing

### Checks

- Reinstall the plugin so `hooks.json` is refreshed
- Verify the hook is invoking `codex exec --ephemeral -s read-only`
- Retry in a normal project directory with write access to `.memsearch/`

### Why this happens

The plugin isolates summarization to avoid contaminating the main Codex session, but the hook still needs enough filesystem access to write memory output.

---

## Memory recall does not trigger

### Checks

- Confirm the skill file was installed correctly
- Ask a history-dependent question rather than a fresh factual question
- Make sure `.memsearch/memory/` already contains prior summaries

### Why this happens

The recall path is skill-driven. If the skill is missing, or there is no prior memory to search, Codex will behave like a stateless assistant.
