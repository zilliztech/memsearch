<!--
  memsearch-dsh memory-recall skill body.
  Registered by plugins/dsh/index.js via ctx.skills.registerProvider()
  with metadata (name: memory-recall, description, whenToUse) supplied in code.
  {{PLACEHOLDER}} tokens are substituted for the calling workspace when loaded.
-->

# Memory Recall

Search memsearch's persistent memory for context relevant to the user's question. The memory store is shared across agents (Claude Code, Codex, OpenClaw, OpenCode, DeepSeek Harness), so it can surface past work, decisions, and conversation fragments from any of them.

## When to use

Use this skill when the user's question could benefit from historical context: they reference past work, ask what was done before, or the current task could reuse earlier decisions or findings. A search is cheap (one index query), so when in doubt, run it.

## Steps

### 1. Search for relevant chunks

Run a semantic search over the project's memsearch collection. The plugin derives the collection from the current working directory when this skill is loaded:

```bash
{{MEMSEARCH_CMD}} search "{{QUERY}}" --top-k 5 --json-output {{MILVUS_FLAG}}--default-collection "{{COLLECTION}}"
```

Before each search, check whether `~/.memsearch/config.toml` or the project's
`.memsearch.toml` exists. If neither exists, add `--provider onnx` to the command.
Otherwise, leave the provider unset so the existing configuration applies.

Replace `{{QUERY}}` with a concise natural-language summary of what the user needs. The `--json-output` results contain `content`, `source`, `heading`, `score`, and `chunk_hash`.

### 2. Expand promising results

For the most promising results, expand the full markdown section to see surrounding context:

```bash
{{MEMSEARCH_CMD}} expand <chunk_hash> {{MILVUS_FLAG}}--default-collection "{{COLLECTION}}"
```

### 3. Drill into the original conversation (optional)

When an expanded result contains an anchor comment like

```
<!-- session:<id> turn:<N> db:<path> -->
```

you can render the original conversation around that turn:

```bash
{{PYTHON_CMD}} "{{PLUGIN_DIR}}/scripts/parse-transcript.py" --db "<path>" --turn <N> --context 3
```

Pass `--context 0` for just the target turn, or omit `--turn` to see the most recent turns.

### 4. Report a curated summary

Return a concise summary of the relevant context to the user, citing the memory source files where useful. If the search finds nothing relevant, say so plainly in one line and proceed without it. Do not fabricate memories.

## Notes

- The memory store is plain markdown under `<project>/.memsearch/memory/YYYY-MM-DD.md`. Milvus is a derived search index; a chunk may be indexed slightly behind the markdown source.
- If `memsearch` is not on PATH, prefix with the detected command `{{MEMSEARCH_CMD}}` (which may be `uvx --from 'memsearch[onnx]' memsearch`).
- Prefer the final, user-facing outcome over raw transcript detail.
