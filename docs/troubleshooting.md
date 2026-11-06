# Troubleshooting

This page covers common **memsearch core** issues that affect the Python library, CLI, and platform plugins alike. For plugin-specific hook/runtime issues, see the individual platform troubleshooting pages.

## Search returns no results

Start with basic index health checks:

```bash
memsearch stats
memsearch search "your query here" --top-k 5
```

If `stats` shows 0 or the count is unexpectedly low, rebuild the index:

```bash
memsearch index . --force
```

Common causes:

- the relevant markdown files were never indexed
- the index is stale and needs re-indexing
- the query is too short or vague
- the embedding provider/model changed after the collection was created

## Dimension mismatch

A dimension mismatch means the existing Milvus collection was created with one embedding dimension, but your current embedding provider/model is producing a different vector size.

Typical fix:

```bash
memsearch reset --yes
memsearch index .
```

This is safe because your markdown files are the source of truth; resetting only drops the vector index.

## API key missing

If you use a hosted embedding provider, make sure the expected API key is present.

Common environment variables:

- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `VOYAGE_API_KEY`

If you do not want to manage API keys, switch to a local provider such as ONNX, Ollama, or `local` sentence-transformers.

## Windows + Milvus Lite

Milvus Lite 3.x provides a Windows-capable foundation, and memsearch installs `milvus-lite>=3.1.1` with `pymilvus>=2.6.11` on Windows. The local path is best-effort because the memsearch maintainers have not completed one-to-one native Windows validation; it is not part of the formal support matrix.

If the local backend fails, use one of these alternatives:

- Milvus Server via Docker
- Zilliz Cloud
- WSL2 for a Linux-based Milvus Lite workflow

See [Getting Started — Milvus Backends](getting-started.md#milvus-backends).

## Milvus Lite collection is released

If `memsearch search`, `memsearch index`, or `memsearch expand` fails with an error like this:

```text
Collection '...' is in state 'released'; call load() before search/get/query
```

Upgrade memsearch first. Current memsearch versions explicitly load existing Milvus collections before query/search operations.

If this started after upgrading Milvus Lite, check whether the local `.db` file was created by an older Milvus Lite release. Milvus Lite 3.x uses a different storage layout and cannot automatically migrate a 2.x `.db` file. Preserve the old database and your source markdown, move the database aside manually, then rebuild the derived index from markdown:

=== "macOS / Linux"

    ```bash
    mv ~/.memsearch/milvus.db ~/.memsearch/milvus.db.bak
    memsearch index . --force
    ```

=== "Windows PowerShell"

    ```powershell
    Move-Item "$HOME\.memsearch\milvus.db" "$HOME\.memsearch\milvus.db.bak"
    memsearch index . --force
    ```

Do not delete the old database until the rebuilt index has been verified. Memsearch does not perform an in-place 2.x-to-3.x migration. Collection descriptions are also best-effort metadata in Lite 3.x: an empty value from `describe_collection()` does not indicate an indexing or search failure.

Alternatively, keep using the older Milvus Lite environment that created the `.db` file, or switch to Milvus Server via Docker / Zilliz Cloud.

## Rebuild from source markdown

To wipe the current collection and rebuild from markdown files:

```bash
memsearch reset --yes
memsearch index .
```

Useful when:

- you switched embedding providers/models
- search quality looks wrong after a configuration change
- you want to confirm the stored vectors match the current source markdown

## Inspect what is indexed

Use `stats` for a quick count:

```bash
memsearch stats
```

Then inspect actual content with progressive disclosure:

```bash
memsearch search "redis ttl"
memsearch expand <chunk_id>
```

## Remote Milvus stats look stale

On remote Milvus Server / Zilliz Cloud, `stats` may lag immediately after upserts because collection stats update after flush/compaction.

Search results are still the better source of truth for "is my content searchable right now?"

## First local model download is slow

Local embedding setups such as ONNX may need to download model artifacts on first use. That initial run can feel slow compared with later runs.

If you want to warm the cache ahead of time, run a dummy command once:

```bash
memsearch search "warmup"
```

## `memsearch index` aborts after printing "Indexed N chunks."

On macOS with the `onnx` provider, an index run could finish, write every row, and then die with `Abort trap: 6` (exit 134), so callers that check the exit code saw a failure on complete data.

The abort came from onnxruntime's own telemetry uploader, whose worker thread can outlive interpreter shutdown. memsearch now calls `onnxruntime.disable_telemetry_events()` before it creates any inference session, so no usage events are uploaded from an ONNX embedding or reranking run.
