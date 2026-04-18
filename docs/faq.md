# FAQ

## Does memsearch work on Windows?

Yes, but **Milvus Lite** (the default local `.db` backend) does not provide Windows binaries.

If you are on Windows, use one of these options instead:

- **Milvus Server** via Docker
- **Zilliz Cloud**
- **WSL2** if you specifically want the Milvus Lite local-file workflow

See [Getting Started — Milvus Backends](getting-started.md#milvus-backends) for the backend comparison and recommended setup.

## How do I wipe and rebuild the index?

Use `memsearch reset --yes` to drop the current collection, then run `memsearch index` again.

```bash
memsearch reset --yes
memsearch index .
```

This deletes the indexed chunks in Milvus, but it does **not** delete your source markdown files.

For command details, see the [CLI reference](cli.md#memsearch-reset).

## How do I see what is indexed?

Start with index stats:

```bash
memsearch stats
```

That shows the total indexed chunk count for the active collection.

To inspect actual indexed content, run a representative search, then progressively expand results:

```bash
memsearch search "redis ttl"
memsearch expand <chunk_id>
```

See the [CLI reference](cli.md#memsearch-stats) for `stats`, and the `search` / `expand` sections for content inspection workflows.

## Why is search returning irrelevant results?

Common causes:

- the current embedding provider does not match the kind of content you indexed
- the index is stale and needs re-indexing
- your query is too short or too vague
- you switched providers/models and are still searching an old index

Practical things to try:

1. Re-index your memory files: `memsearch index . --force`
2. Make the query more specific
3. Check which embedding provider you configured
4. If you recently changed providers, consider resetting and rebuilding the index

See [Configuration](home/configuration.md) for embedding provider options.

## What does "dimension mismatch" mean, and how do I fix it?

A dimension mismatch means your existing Milvus collection was created with one embedding dimension, but your current embedding provider/model is producing vectors with a different dimension.

The usual fix is to reset the collection and re-index from source markdown files:

```bash
memsearch reset --yes
memsearch index .
```

Because markdown is the source of truth, rebuilding the vector index is safe as long as your original memory files are still present.
