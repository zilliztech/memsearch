# Python API

memsearch provides a high-level Python API through the `MemSearch` class. Import it, point it at your markdown files, and you get semantic memory for your agent in a few lines of code.

```python
from memsearch import MemSearch

mem = MemSearch(paths=["./memory"])

await mem.index()                                      # index markdown files
results = await mem.search("Redis config", top_k=3)    # semantic search
print(results[0]["content"], results[0]["score"])       # content + similarity
```

---

## `MemSearch`

The main entry point. Handles indexing, search, compaction, and file watching.

### Constructor

```python
MemSearch(
    paths=["./memory"],
    *,
    embedding_provider="openai",
    embedding_model=None,
    milvus_uri="~/.memsearch/milvus.db",
    milvus_token=None,
    collection="memsearch_chunks",
    max_chunk_size=1500,
    overlap_lines=2,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `paths` | `list[str \| Path]` | `[]` | Directories or files to index |
| `embedding_provider` | `str` | `"openai"` | Embedding backend (`"openai"`, `"google"`, `"voyage"`, `"ollama"`, `"local"`) |
| `embedding_model` | `str \| None` | `None` | Override the default model for the chosen provider |
| `milvus_uri` | `str` | `"~/.memsearch/milvus.db"` | Milvus connection URI — local `.db` path for Milvus Lite (Linux/macOS only), `http://host:port` for Milvus Server, or `https://*.zillizcloud.com` for Zilliz Cloud |
| `milvus_token` | `str \| None` | `None` | Auth token for Milvus Server or Zilliz Cloud |
| `collection` | `str` | `"memsearch_chunks"` | Milvus collection name. Use different names to isolate agents sharing the same backend |
| `max_chunk_size` | `int` | `1500` | Maximum chunk size in characters |
| `overlap_lines` | `int` | `2` | Overlapping lines between adjacent chunks |

### Context Manager

`MemSearch` implements the context manager protocol. Use `with` to ensure resources are released:

```python
with MemSearch(paths=["./memory"]) as mem:
    await mem.index()
    results = await mem.search("Redis config")
# Milvus connection is closed automatically
```

Or call `mem.close()` manually when done.

---

## Methods

### `index`

```python
await mem.index(*, force=False) -> int
```

Scan all configured paths and index every markdown file (`.md`, `.markdown`) into the vector store. Returns the number of chunks indexed.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `force` | `bool` | `False` | Re-embed all chunks even if unchanged. Use this after switching embedding providers |

**Behavior:**

- **Incremental by default.** Only new or changed chunks are embedded. Unchanged chunks are skipped via content-hash dedup.
- **Stale cleanup.** Chunks from deleted files are automatically removed.
- **Deleted content.** If a section is removed from a file, its old chunks are cleaned up on the next `index()` call.

```python
mem = MemSearch(paths=["./memory", "./notes"])
n = await mem.index()
print(f"Indexed {n} chunks")

# After switching to a different embedding provider, force re-index
n = await mem.index(force=True)
```

---

### `index_file`

```python
await mem.index_file(path) -> int
```

Index a single file. Returns the number of chunks indexed.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str \| Path` | Path to a markdown file |

```python
n = await mem.index_file("./memory/2026-02-12.md")
```

---

### `search`

```python
await mem.search(query, *, top_k=10) -> list[dict]
```

Semantic search across indexed chunks. Returns a list of result dicts, sorted by relevance.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | *(required)* | Natural-language search query |
| `top_k` | `int` | `10` | Maximum number of results |

**Return value:** Each dict contains:

| Key | Type | Description |
|-----|------|-------------|
| `content` | `str` | The chunk text |
| `source` | `str` | Path to the source markdown file |
| `heading` | `str` | The heading this chunk belongs to |
| `heading_level` | `int` | Heading level (1–6, or 0 for no heading) |
| `chunk_hash` | `str` | Unique chunk identifier |
| `start_line` | `int` | Start line in the source file |
| `end_line` | `int` | End line in the source file |
| `score` | `float` | Relevance score (higher is better) |

```python
results = await mem.search("who is the frontend lead?", top_k=5)
for r in results:
    print(f"[{r['score']:.4f}] {r['heading']}: {r['content'][:100]}")
```

---

### `compact`

```python
await mem.compact(
    *,
    source=None,
    llm_provider="openai",
    llm_model=None,
    prompt_template=None,
    output_dir=None,
) -> str
```

Use an LLM to compress indexed chunks into a summary. The summary is appended to `memory/YYYY-MM-DD.md` and automatically indexed.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str \| None` | `None` | Only compact chunks from this source file. `None` = all chunks |
| `llm_provider` | `str` | `"openai"` | LLM backend (`"openai"`, `"anthropic"`, `"gemini"`) |
| `llm_model` | `str \| None` | `None` | Override the default LLM model |
| `prompt_template` | `str \| None` | `None` | Custom prompt (must contain `{chunks}` placeholder) |
| `output_dir` | `str \| Path \| None` | `None` | Where to write the summary. Defaults to the first configured path |

**Default LLM models:**

| Provider | Default Model |
|----------|--------------|
| `openai` | `gpt-4o-mini` |
| `anthropic` | `claude-sonnet-4-5-20250929` |
| `gemini` | `gemini-2.0-flash` |

```python
# Compact all memories
summary = await mem.compact()
print(summary)

# Compact only one file, using Claude
summary = await mem.compact(
    source="./memory/old-notes.md",
    llm_provider="anthropic",
)
```

---

### `watch`

```python
mem.watch(*, on_event=None, debounce_ms=None) -> FileWatcher
```

Start a background file watcher that auto-indexes markdown changes. This is a **synchronous** method that returns a `FileWatcher` object running in a background thread.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `on_event` | `Callable` | `None` | Callback invoked after each event: `(event_type, summary, file_path)`. `event_type` is `"created"`, `"modified"`, or `"deleted"` |
| `debounce_ms` | `int \| None` | `None` | Debounce delay in milliseconds. Defaults to 1500 if not set |

**Returns:** a `FileWatcher` instance. Call `watcher.stop()` to stop watching, or use it as a context manager.

```python
mem = MemSearch(paths=["./memory"])
await mem.index()  # initial index

# Start watching for changes in the background
watcher = mem.watch(on_event=lambda t, s, p: print(f"[{t}] {s}"))

# ... your agent runs here ...

watcher.stop()
```

---

### `close`

```python
mem.close() -> None
```

Release the Milvus connection and other resources. Called automatically when using `MemSearch` as a context manager.

---

## Full Example

A complete agent loop: seed knowledge, index it, then recall it during conversation.

=== "OpenAI"

    ```python
    import asyncio
    from datetime import date
    from pathlib import Path
    from openai import OpenAI
    from memsearch import MemSearch

    MEMORY_DIR = "./memory"
    llm = OpenAI()
    mem = MemSearch(paths=[MEMORY_DIR])

    def save_memory(content: str):
        """Append a note to today's memory log."""
        p = Path(MEMORY_DIR) / f"{date.today()}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(f"\n{content}\n")

    async def agent_chat(user_input: str) -> str:
        # 1. Recall — search past memories
        memories = await mem.search(user_input, top_k=3)
        context = "\n".join(f"- {m['content'][:200]}" for m in memories)

        # 2. Think — call LLM with memory context
        resp = llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You have these memories:\n{context}"},
                {"role": "user", "content": user_input},
            ],
        )
        answer = resp.choices[0].message.content

        # 3. Remember — save and index
        save_memory(f"## {user_input}\n{answer}")
        await mem.index()
        return answer

    async def main():
        save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
        save_memory("## Decision\nWe chose Redis for caching over Memcached.")
        await mem.index()  # or mem.watch() to auto-index in the background

        print(await agent_chat("Who is our frontend lead?"))
        print(await agent_chat("What caching solution did we pick?"))

    asyncio.run(main())
    ```

=== "Anthropic Claude"

    ```python
    import asyncio
    from datetime import date
    from pathlib import Path
    from anthropic import Anthropic
    from memsearch import MemSearch

    MEMORY_DIR = "./memory"
    llm = Anthropic()
    mem = MemSearch(paths=[MEMORY_DIR])

    def save_memory(content: str):
        p = Path(MEMORY_DIR) / f"{date.today()}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(f"\n{content}\n")

    async def agent_chat(user_input: str) -> str:
        memories = await mem.search(user_input, top_k=3)
        context = "\n".join(f"- {m['content'][:200]}" for m in memories)

        resp = llm.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system=f"You have these memories:\n{context}",
            messages=[{"role": "user", "content": user_input}],
        )
        answer = resp.content[0].text

        save_memory(f"## {user_input}\n{answer}")
        await mem.index()
        return answer

    async def main():
        save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
        await mem.index()
        print(await agent_chat("Who is our frontend lead?"))

    asyncio.run(main())
    ```

=== "Ollama (fully local)"

    ```python
    import asyncio
    from datetime import date
    from pathlib import Path
    from ollama import chat
    from memsearch import MemSearch

    MEMORY_DIR = "./memory"
    mem = MemSearch(paths=[MEMORY_DIR], embedding_provider="ollama")

    def save_memory(content: str):
        p = Path(MEMORY_DIR) / f"{date.today()}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(f"\n{content}\n")

    async def agent_chat(user_input: str) -> str:
        memories = await mem.search(user_input, top_k=3)
        context = "\n".join(f"- {m['content'][:200]}" for m in memories)

        resp = chat(
            model="llama3.2",
            messages=[
                {"role": "system", "content": f"You have these memories:\n{context}"},
                {"role": "user", "content": user_input},
            ],
        )
        answer = resp.message.content

        save_memory(f"## {user_input}\n{answer}")
        await mem.index()
        return answer

    async def main():
        save_memory("## Team\n- Alice: frontend lead\n- Bob: backend lead")
        await mem.index()
        print(await agent_chat("Who is our frontend lead?"))

    asyncio.run(main())
    ```
