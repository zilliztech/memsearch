<!--
  memsearch-dsh memory-recall skill body.
  Registered at plugin load by plugins/dsh/index.js via ctx.skills.register()
  with metadata (name: memory-recall, description, whenToUse) supplied in code.
  {{PLACEHOLDER}} tokens are substituted at registration time.
-->

# Memory Recall

Search memsearch's persistent memory for context relevant to the user's question. The memory store is shared across agents (Claude Code, Codex, OpenClaw, OpenCode, DeepSeek Harness), so it can surface past work, decisions, and conversation fragments from any of them.

## When to use

Use this skill when the user's question could benefit from historical context: they reference past work, ask what was done before, or the current task could reuse earlier decisions or findings. A search is cheap (one index query), so when in doubt, run it.

## Steps

### 1. Search for relevant chunks

Run a semantic search over the project's memsearch collection. The collection is derived from the project directory (see `derive-collection.sh`); the plugin normally injects the resolved value as `{{COLLECTION}}`:

```bash
{{MEMSEARCH_CMD}} search "{{QUERY}}" --top-k 5 --json-output {{MILVUS_FLAG}}--default-collection "{{COLLECTION}}"
```

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
{{PYTHON_CMD}} {{PLUGIN_DIR}}/scripts/parse-transcript.py --db "<path>" --turn <N> --context 3
```

Pass `--context 0` for just the target turn, or omit `--turn` to see the most recent turns.

### 4. Report a curated summary

Return a concise summary of the relevant context to the user, citing the memory source files where useful. If the search finds nothing relevant, say so plainly in one line and proceed without it. Do not fabricate memories.

## Notes

- The memory store is plain markdown under `<project>/.memsearch/memory/YYYY-MM-DD.md`. Milvus is a derived search index; a chunk may be indexed slightly behind the markdown source.
- The commands above work in bash and PowerShell alike: `{{MEMSEARCH_CMD}}` and `{{PYTHON_CMD}}` are pre-resolved for this machine. If `memsearch` is not on PATH, the prefix may be a `uvx --from 'memsearch[onnx]' memsearch` fallback.
- Prefer the final, user-facing outcome over raw transcript detail.
