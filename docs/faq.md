# FAQ

---

## Can I use memsearch for per-user memory in a consumer-facing app?

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

Each user's memories live in their own directory and their own collection. They never see each other's data.

**Option 2 — Separate Milvus Lite databases (strongest isolation):**

```python
def get_user_memory(user_id: str) -> MemSearch:
    return MemSearch(
        paths=[f"./memory/{user_id}"],
        milvus_uri=f"./data/{user_id}.db",
    )
```

Each user gets a physically separate database file. This is the simplest model when you don't need cross-user search.

The [Claude Code plugin](claude-plugin.md) uses per-project isolation — each project automatically gets its own Milvus collection (e.g. `ms_my_app_a1b2c3d4`) derived from the project path, so searches never leak across projects. But the underlying memsearch library has no such constraint — a consumer chat app can instantiate one `MemSearch` per user and get clean isolation.

---

## How do multiple developers share memory on the same project?

Short answer: **they don't need to, and usually shouldn't.**

In a typical multi-developer workflow, each person clones the repo locally and runs their own Claude Code sessions. The plugin stores memory in `.memsearch/memory/YYYY-MM-DD.md` files — these are **personal session logs** generated from each developer's own conversations. They are local by nature and do not need to be pushed to the shared remote.

Here is how we think about it in our own team:

| What | Scope | Version-controlled? | Example |
|------|-------|---------------------|---------|
| **Project conventions** | Shared across team | Yes — commit to git | `CLAUDE.md` (coding standards, architecture decisions, team agreements) |
| **Session memories** | Personal to each developer | No — add to `.gitignore` | `.memsearch/memory/2026-02-10.md` (what *you* worked on today) |

```gitignore
# .gitignore
.memsearch/
```

**Why this works:**

- **No merge conflicts.** Each developer's memory files only exist on their own machine. There is nothing to merge.
- **No noise.** Your colleagues don't need to know that you spent 45 minutes debugging a typo. Your session logs are yours.
- **Shared knowledge goes in `CLAUDE.md`.** Decisions that the whole team should know about (e.g., "we use Redis for caching", "never use `SELECT *`") belong in `CLAUDE.md` or a shared docs directory — version-controlled, reviewed via PR, the normal git workflow.

If your team *does* want to share certain memories (e.g., onboarding notes, architecture decisions), you can put those in a shared directory that is tracked by git, and keep personal session logs in `.memsearch/` which is gitignored. memsearch can index multiple paths, so you can point it at both:

```python
mem = MemSearch(paths=["./docs/shared-knowledge", "./.memsearch/memory"])
```

---

## How does memsearch avoid re-embedding unchanged content?

Embedding API calls are the main cost of running a semantic search system. memsearch uses **content-addressable hashing** to ensure you never pay to embed the same content twice.

Here is the mechanism:

1. **Chunk the file.** Each markdown file is split into chunks by heading structure (h1/h2/h3 boundaries).

2. **Hash each chunk.** The content of each chunk is hashed with SHA-256 (truncated to 16 hex characters). This hash is combined with the source path, line range, and embedding model name to produce a **composite chunk ID**.

3. **Check against Milvus.** Before calling the embedding API, memsearch queries Milvus for all existing chunk IDs belonging to that source file.

4. **Skip unchanged chunks.** If a chunk's composite ID already exists in Milvus, it is skipped entirely — no embedding API call, no upsert.

5. **Delete stale chunks.** If a chunk ID that used to exist no longer appears in the re-chunked file, it is deleted from Milvus (the content was removed or changed).

```
file changed → re-chunk → hash each chunk → diff against Milvus
                                                  │
                                    ┌─────────────┼─────────────┐
                                    │             │             │
                              ID exists      ID is new    ID disappeared
                              (skip)      (embed + upsert)  (delete)
```

**In practice, this means:**

- **Re-indexing an unchanged knowledge base costs zero API calls.** The hashes match, everything is skipped.
- **Editing one section of a file only re-embeds that section's chunks.** The rest of the file is untouched.
- **The file watcher (`memsearch watch`) uses this same mechanism.** When it detects a file change, it re-chunks and re-hashes — only the actually-changed chunks hit the embedding API.

For more details on the hashing scheme and storage architecture, see the [Architecture — Deduplication](architecture.md#deduplication) page.
