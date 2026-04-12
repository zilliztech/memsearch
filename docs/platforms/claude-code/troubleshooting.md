# Troubleshooting

This page covers common issues when using the memsearch Claude Code plugin. For general memsearch issues (CLI, embedding, Milvus), see the relevant sections in [Getting Started](../../getting-started.md) and [CLI Reference](../../cli.md).

---

## Status Line

The plugin displays a status line at session start:

**Normal:**
```
[memsearch v0.2.9] embedding: onnx/unknown | milvus: ~/.memsearch/milvus.db | collection: ms_myproject_a1b2c3
```

**API key missing:**
```
[memsearch v0.2.9] embedding: openai/text-embedding-3-small | milvus: ~/.memsearch/milvus.db | ERROR: OPENAI_API_KEY not set
```

**Update available:**
```
[memsearch v0.2.9] ... | UPDATE: v0.2.10 available -- run: uv tool upgrade memsearch
```

### "ERROR: \<KEY\> not set"

The plugin checks for the required API key at session start. Memory recording still writes `.md` files, but semantic search and indexing are disabled.

| Provider | Required Env Var |
|----------|-----------------|
| `onnx` (default) | None (local, CPU) |
| `openai` | `OPENAI_API_KEY` |
| `google` | `GOOGLE_API_KEY` |
| `voyage` | `VOYAGE_API_KEY` |
| `ollama` | None (local) |
| `local` | None (local) |

**Fix:** Export the key or switch to a local provider:

```bash
# Option 1: Set the API key
export OPENAI_API_KEY="sk-..."

# Option 2: Switch to free local embedding (no key needed)
memsearch config set embedding.provider onnx
```

---

## Debug Mode

Start Claude Code with `--debug` to see full hook JSON output:

```bash
claude --debug
```

**Log location:** `~/.claude/logs/`

```bash
grep -A 5 'hook' ~/.claude/logs/*.log          # all hook outputs
grep 'additionalContext' ~/.claude/logs/*.log   # cold-start context injection
```

---

## CLI Diagnostic Commands

These work outside of any agent session -- run them directly in your terminal.

**Verify configuration:**
```bash
memsearch config list --resolved
```

**Check index health:**
```bash
memsearch stats
```

If count is 0 or unexpectedly low:
```bash
memsearch index .memsearch/memory/ --force
```

**Test search manually:**
```bash
memsearch search "your query here" --top-k 5
```

If search returns no results but `stats` shows chunks exist, the issue is likely:

- Wrong API key or embedding provider
- Different embedding model than what was used for indexing

**Expand a chunk:**
```bash
memsearch expand <chunk_hash>
```

**Trace back to original conversation:**
```bash
memsearch transcript /path/to/session.jsonl --turn <uuid> --context 3
```

---

## Watch Process

The `memsearch watch` singleton runs in the background, auto-re-indexing when memory files change.

**PID file:** `.memsearch/.watch.pid`

**Check if running:**
```bash
cat .memsearch/.watch.pid && kill -0 $(cat .memsearch/.watch.pid) 2>/dev/null && echo "running" || echo "not running"
```

**Restart manually:**
```bash
kill $(cat .memsearch/.watch.pid) 2>/dev/null; rm -f .memsearch/.watch.pid
memsearch watch .memsearch/memory/ &
echo $! > .memsearch/.watch.pid
```

**Find orphaned processes:**
```bash
pgrep -f "memsearch watch" && echo "found orphans" || echo "clean"
```

!!! note
    Milvus Lite does not support concurrent access, so plugins fall back to one-time indexing at session start. For real-time indexing, use [Milvus Server or Zilliz Cloud](../../getting-started.md#milvus-backends).

---

## Memory Recall Not Triggering

Try invoking the skill manually:

```
/memory-recall <your query>
```

If manual invocation works but auto-invocation doesn't:

- Claude judged the question doesn't need historical context (by design)
- Check that the prompt is >= 10 characters (short prompts skip the memory hint)
- Verify `memsearch` is in PATH

---

## Memory Files Missing or Empty

All memories are written to `.memsearch/memory/YYYY-MM-DD.md`.

**Verify files exist:**
```bash
ls -la .memsearch/memory/
cat .memsearch/memory/$(date +%Y-%m-%d).md
```

**If you see session headings but no bullet-point summaries:**

| Cause | Fix |
|-------|-----|
| `claude` CLI not found | Ensure `claude` is in PATH |
| Transcript too short (< 3 lines) | Normal for very short sessions |
| Stop hook timed out | Check `~/.claude/logs/` for errors |

---

## First-Time Model Download

The ONNX bge-m3 int8 model (~558 MB) downloads from HuggingFace Hub on first use.

**Symptoms:**

- First session hangs after sending a prompt
- `memsearch search` or `memsearch index` hang on first run
- `[memsearch] Memory available` appears but recall returns no results

**Pre-download:**
```bash
uvx --from 'memsearch[onnx]' memsearch search --provider onnx "warmup" 2>/dev/null || true
```

**If download is slow:**
```bash
export HF_ENDPOINT=https://hf-mirror.com
uvx --from 'memsearch[onnx]' memsearch search --provider onnx "warmup" 2>/dev/null || true
```

After the first download, the model is cached at `~/.cache/huggingface/hub/` and loads instantly.

---

## Quick Reference

| Symptom | Check | Fix |
|---------|-------|-----|
| "ERROR: KEY not set" in status | Export the required API key | `export OPENAI_API_KEY="sk-..."` or switch to `onnx` |
| Search returns no results | `memsearch stats` + manual search | Re-index with `memsearch index .memsearch/memory/ --force` |
| New memories not indexed | Watch process status | Check `.memsearch/.watch.pid`, restart if needed |
| Skill never triggers automatically | Manual `/memory-recall` test | Ensure prompt >= 10 chars; memsearch in PATH |
| First session hangs | ONNX model downloading | Pre-download with warmup command |
| Session summaries missing | Check `claude` CLI availability | Verify `claude` is in PATH |
| Stale stats count | Normal for Milvus Server | Stats update after flush/compaction; search is always up-to-date |
