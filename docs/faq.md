# FAQ & Troubleshooting

Common questions about memsearch and the Claude Code plugin. If you hit an error not covered here, check the [CLI Reference](cli.md) or open an [issue](https://github.com/zilliztech/memsearch/issues).

---

## Installation & Platform Support

### Does memsearch work on Windows?

**Not with the default backend.** Milvus Lite (the embedded local database used by default) does not publish Windows binaries ([milvus-lite#176](https://github.com/milvus-io/milvus-lite/issues/176)).

On Windows you have three options:

| Option | How |
|--------|-----|
| **Milvus Server via Docker** | `docker run -d -p 19530:19530 milvusdb/milvus:latest milvus run standalone`, then use `milvus_uri="http://localhost:19530"` |
| **Zilliz Cloud** | Free tier at [cloud.zilliz.com](https://cloud.zilliz.com) — no local server needed |
| **WSL2** | Run memsearch inside [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) — Milvus Lite works on Linux |

See [Milvus Backends](getting-started.md#milvus-backends) for connection examples.

---

### Which platforms does Milvus Lite support?

Milvus Lite (the default `~/.memsearch/milvus.db` backend) supports **Linux** and **macOS** only. For Windows, use Milvus Server or Zilliz Cloud.

---

## Index & Search

### How do I wipe and rebuild the index from scratch?

```bash
# Drop all indexed data
memsearch reset --yes

# Re-index everything
memsearch index ./memory/
```

Use this when switching embedding providers (the old vectors are incompatible with the new model), or when the index gets into a bad state.

### How do I see what is currently indexed?

```bash
# Total chunk count
memsearch stats

# Detailed view: search for anything with a broad query
memsearch search "." --top-k 20 --json-output | python -m json.tool
```

### Why is search returning irrelevant results?

The most common causes:

1. **Provider/model mismatch** — the provider used for `search` must match the one used for `index`. If you indexed with `openai` and search with `google`, the vector spaces are incompatible. Fix: `memsearch reset --yes && memsearch index . --provider <correct-provider>`

2. **Index is stale** — new files were added but not indexed. Fix: `memsearch index .`

3. **Chunks are too large or too small** — try adjusting `max_chunk_size` in your config. Default is 1500 characters. Smaller chunks = more precise results; larger chunks = more context per result.

4. **Query is too vague** — hybrid search (dense + BM25) works best with specific, natural-language queries. Try rephrasing with more domain-specific terms.

### What is "dimension mismatch" and how do I fix it?

This error occurs when the vector dimensions stored in Milvus (from a previous embedding model) don't match the dimensions of the current model. For example, switching from OpenAI (`text-embedding-3-small`, 1536 dims) to a local model (`all-MiniLM-L6-v2`, 384 dims).

Fix:

```bash
memsearch reset --yes       # drops the old collection
memsearch index ./memory/   # re-embeds with the new model
```

See the [Embedding Provider Reference](cli.md#embedding-provider-reference) for dimensions per provider.

### What is the difference between `memsearch index` and `memsearch watch`?

| Command | When to use |
|---------|-------------|
| `memsearch index` | One-shot: scan and index all files now, then exit |
| `memsearch watch` | Long-running: index now, then monitor for file changes and auto-re-index |

`watch` uses the same content-hash dedup as `index` — unchanged files produce zero API calls on startup. Use `watch` alongside editors or agent processes that continuously write to your knowledge base. See [CLI Reference — watch](cli.md#memsearch-watch).

---

## Per-User and Multi-Developer Use

### Can I use memsearch for per-user memory in a consumer-facing app?

**Yes.** memsearch is not locked to a "per-project" or "per-agent" model. The `paths`, `collection`, and `milvus_uri` parameters can all be set dynamically per user, giving you full per-user isolation.

**Option 1 — Directory + collection isolation (recommended):**

```python
from memsearch import MemSearch

def get_user_memory(user_id: str) -> MemSearch:
    return MemSearch(
        paths=[f"./memory/{user_id}"],
        collection=f"mem_{user_id}",
    )

# Fully isolated — different markdown directories, different Milvus collections
mem_alice = get_user_memory("alice")
mem_bob = get_user_memory("bob")
```

**Option 2 — Separate Milvus Lite databases (strongest isolation):**

```python
def get_user_memory(user_id: str) -> MemSearch:
    return MemSearch(
        paths=[f"./memory/{user_id}"],
        milvus_uri=f"./data/{user_id}.db",
    )
```

### How do multiple developers share memory on the same project?

Short answer: **they don't need to, and usually shouldn't.**

In a typical multi-developer workflow, each person clones the repo locally and runs their own Claude Code sessions. The plugin stores memory in `.memsearch/memory/YYYY-MM-DD.md` files — these are **personal session logs** generated from each developer's own conversations.

| What | Scope | Version-controlled? | Example |
|------|-------|---------------------|---------|
| **Project conventions** | Shared across team | Yes — commit to git | `CLAUDE.md` (coding standards, architecture decisions) |
| **Session memories** | Personal to each developer | No — add to `.gitignore` | `.memsearch/memory/2026-02-10.md` |

```gitignore
# .gitignore
.memsearch/
```

If your team *does* want to share certain memories (e.g., onboarding notes, architecture decisions), put those in a shared directory tracked by git, and keep personal session logs in `.memsearch/` which is gitignored:

```python
mem = MemSearch(paths=["./docs/shared-knowledge", "./.memsearch/memory"])
```

---

## Deduplication & Cost

### How does memsearch avoid re-embedding unchanged content?

memsearch uses **content-addressable hashing** to skip unchanged chunks:

1. Each chunk is hashed with SHA-256 (truncated to 16 hex characters).
2. A **composite chunk ID** is computed from source path + line range + content hash + embedding model name.
3. Before calling the embedding API, existing chunk IDs for that file are queried from Milvus.
4. Chunks whose ID already exists → **skipped** (no API call, no upsert).
5. Chunks whose ID no longer exists → **deleted** (stale chunk cleanup).

```
file changed → re-chunk → hash each chunk → diff against Milvus
                                                  │
                                    ┌─────────────┼─────────────┐
                                    │             │             │
                              ID exists      ID is new    ID disappeared
                              (skip)      (embed + upsert)  (delete)
```

In practice: re-running `memsearch index` on an unchanged knowledge base costs **zero API calls**.

For more details see [Architecture — Deduplication](architecture.md#deduplication).

---

## Troubleshooting

### `ConnectionConfigException` or can't connect to Milvus

The default backend (`~/.memsearch/milvus.db`) requires Milvus Lite, which is only available on Linux and macOS. On Windows this error is expected.

**Fix:** use Milvus Server via Docker or Zilliz Cloud — see [Does memsearch work on Windows?](#does-memsearch-work-on-windows).

If you're on Linux/macOS and still see this, check that the path is writable:

```bash
ls -la ~/.memsearch/
memsearch config get milvus.uri
```

### `API key not set` / `AuthenticationError`

memsearch reads API keys from standard environment variables. The key must be set **before** running memsearch:

```bash
export OPENAI_API_KEY="sk-..."
memsearch index ./memory/
```

See the [full API key table](cli.md#api-keys) for all providers.

To avoid API keys entirely, use a local provider:

```bash
pip install "memsearch[local]"
memsearch index ./memory/ --provider local
```

### `ImportError: No module named 'milvus_lite'` on Windows

Milvus Lite has no Windows binaries. Install memsearch without the default Milvus Lite dependency:

```bash
pip install pymilvus          # without milvus-lite
pip install memsearch         # then memsearch
```

Then connect to Milvus Server or Zilliz Cloud instead of using the default local URI.

### Search returns no results after switching embedding providers

Switching providers changes vector dimensions and vector spaces — old vectors are incompatible with the new model. Reset and re-index:

```bash
memsearch reset --yes
memsearch index ./memory/ --provider <new-provider>
```

### Claude Code plugin: `realpath: illegal option -- m` (macOS)

This was a bug in `ccplugin/scripts/derive-collection.sh` where the script called `realpath -m`, which is a GNU-only flag not supported by BSD `realpath` on macOS. It is fixed in ccplugin v0.2.1+.

If you see this error, update the plugin:

```bash
# Marketplace install
claude /plugins update memsearch
```

Or manually update the `derive-collection.sh` script as described in [issue #95](https://github.com/zilliztech/memsearch/issues/95).
