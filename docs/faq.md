# FAQ

## Why is my first index slow, when re-indexing is instant?

That asymmetry is by design. Chunk IDs are content-addressable, so a re-index only embeds sections that are new or changed -- on an unchanged knowledge base it embeds nothing. A **cold** index (new machine, wiped collection, or an embedding model change) embeds everything, and with a local provider that cost is dominated by model compute: chunk count x model size.

If a cold index projects to hours, pick a smaller model for that collection, raise `embedding.batch_size`, or accept it as a one-time migration cost. Note that changing `embedding.model` later re-triggers the full cost: the model name is part of every chunk ID.

See [Architecture — Indexing Cost Model](architecture.md#indexing-cost-model) for the full breakdown.

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

## Why do I see "collection is in state 'released'" with Milvus Lite?

Milvus requires a collection to be loaded before `search`, `query`, or `get` operations. Some newer Milvus Lite / PyMilvus combinations reopen an existing local collection in a released state, especially across separate CLI invocations such as:

```bash
memsearch index .
memsearch search "my query"
```

Current memsearch versions explicitly load an existing collection before search/query operations. If you still see this error, upgrade memsearch first.

If the error started after upgrading Milvus Lite itself, also check whether you are reusing a local `.db` file created by an older Milvus Lite release. Milvus Lite 3.x was rewritten with a new pure-Python storage engine, and old `.db` files from the previous storage format are not compatible with the new engine. In that case, move the old `.db` file aside and rebuild from your source markdown files:

```bash
mv ~/.memsearch/milvus.db ~/.memsearch/milvus.db.bak
memsearch index . --force
```

If you do not want to rebuild the local database, keep using the older Milvus Lite environment that created it. For a more stable shared or long-running backend, use Milvus Server via Docker or Zilliz Cloud.

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
