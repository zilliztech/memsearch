# MCP server

`memsearch` ships an MCP (Model Context Protocol) server so that any MCP
client — Codex, Claude Code, DeepSeek Harness, Zed, … — can call memory
search, indexing and the configured embedding / rerank backends **as
tools**.

The server is a first-class part of the package, not a wrapper script: it
calls the same Python API as the CLI (`MemSearch`, `MilvusStore`, the
embedding providers, the rerankers), so results and configuration behave
identically whichever way you drive it.

```bash
memsearch mcp                      # honours ~/.memsearch/config.toml
memsearch mcp -c my_collection     # explicit collection
memsearch mcp --knowledge-db ~/.dsh/storages/knowledge-chunks.sqlite
```

## Connecting a client

### Codex

```toml
# ~/.codex/config.toml
[mcp_servers.memsearch]
command = "memsearch"
args = ["mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 180
```

### Claude Code

```bash
claude mcp add memsearch -- memsearch mcp
```

### DeepSeek Harness

```yaml
# ~/.dsh/profiles/desktop/cordis.patch.yml
- insert:
    - id: memsearch-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: memsearch
        transport: stdio
        command: memsearch
        args: ["mcp"]
```

## Transport

* stdio, JSON-RPC 2.0, **one JSON object per line**, UTF-8.
* MCP does *not* use LSP-style `Content-Length` framing on stdio.
* The server forces UTF-8 on stdin/stdout. On Windows the default pipe
  encoding is the console code page (GBK on a zh-CN machine), which
  corrupts the JSON payload and the Chinese text it carries.

## Tools

| Tool | What it does |
|---|---|
| `memory_search` | Hybrid search (dense + BM25, RRF) over the indexed markdown; reranked when a cross-encoder is configured. |
| `memory_index` | Index markdown files or directories into the collection. |
| `memory_stats` | Chunk count and indexed source files. |
| `memory_expand` | Expand one chunk to its full heading section (progressive disclosure: search → expand → transcript). |
| `embed` | Embed text with the configured provider. |
| `rerank` | Cross-encoder rerank of documents against a query. |
| `knowledge_search` | *Optional* — hybrid search over a DeepSeek Harness knowledge store, exposed only when a store is configured. |

Every tool returns a text block. Invalid arguments come back as
`isError: true` with the reason, never as a crash — one bad call never
kills the server. Result limits must be positive integers, expansion
context must be a non-negative integer, and boolean options require JSON
booleans (for example `false`, not the string `"false"`). Notifications do
not produce replies.

The `rerank` tool requires the remote reranker backend (`remote:` model in
the `[reranker]` config). When that backend is not available, `rerank`
reports an error and `memory_search` returns unreranked results.

If indexing fails for any file, `memory_index` returns `isError: true`
with the indexed chunk count and failed-file details; a partial write is
not reported as an entirely successful call. Subsequent reads reopen the
collection so a collection created by indexing is visible in the same
server session. `embed` uses the embedding provider directly and does not
require a Milvus collection or a matching collection dimension.

### `memory_search`

```jsonc
{
  "query": "校机的向量服务端口",   // required
  "limit": 5,                     // default 5
  "source_prefix": "/home/me/proj" // optional path filter
}
```

The answer is a readable digest; every hit carries its `chunk_hash`, so
`memory_expand` can pull the full context:

```
[1] score=0.9981  /home/me/proj/notes.md  #端口
校机的向量服务跑在 8080 端口。
    (chunk_id=8f3c…  lines 12-18)
```

## Known limitations

A long-lived MCP server session behaves differently from one-shot CLI invocations in three ways. None of them loses data, and your markdown files remain the source of truth throughout.

### A collection created outside the session is not visible

The server caches its Milvus handle on first use, including the answer that the collection does not exist. If `memsearch index` or a platform plugin creates the collection afterwards, the running server keeps reporting it as missing until you call the `memory_index` tool or restart the server.

### The Milvus Lite file is locked while the server runs

With the default local backend (`~/.memsearch/milvus.db`) the server holds the database open for its whole lifetime, so CLI commands against the same file fail until the server exits. If several processes must share one database, use Milvus Server via Docker or Zilliz Cloud.

See [Getting Started — Milvus Backends](getting-started.md#milvus-backends) for the backend comparison.

### Knowledge chunks written during a call appear on the next call

`knowledge_search` answers from a snapshot taken when the call starts. If the dsh-knowledge plugin writes new chunks while a call is in flight, the reply does not include them; the next call does.

## Configuration

The MCP server uses the **same configuration resolution as the CLI**:
`~/.memsearch/config.toml` → project `.memsearch.toml` → CLI flags.

A self-hosted backend behind an SSH tunnel looks like this:

```toml
[embedding]
provider = "openai"                     # OpenAI-compatible endpoint
base_url = "http://127.0.0.1:8080/v1"   # llama.cpp / vLLM / Ollama
api_key = "dummy"
model = "Qwen3-Embedding-4B"

[reranker]
model = "remote:Qwen3-Reranker-0.6B"    # remote cross-encoder
```

The reranker endpoint is read from `MEMSEARCH_REMOTE_RERANKER_URL`
(default `http://127.0.0.1:8081/v1/rerank`).

> **Collection names differ per machine.** The plugins derive the
> collection from the project path (`ms_<dir>_<sha256(path)[:8]>`), so the
> same project on Windows and Linux hashes differently. Pin the name in
> the config to keep them in sync:
>
> ```toml
> [milvus]
> collection = "ms_myproject_1a2b3c4d"
> ```
>
> An explicit config value wins over the `--default-collection` the
> plugins pass.

## The knowledge store tool

`knowledge_search` reads the store of the **third-party
[`dsh-knowledge`](https://github.com/Soren-ABT/dsh-knowledge) DSH plugin** —
not DeepSeek Harness itself. The plugin keeps its chunks in a SQLite file at
`~/.dsh/storages/knowledge-chunks.sqlite`, and the tool queries it with the
same recipe the plugin uses:

1. dense scan over the stored (L2-normalised) vectors,
2. BM25 over the FTS5 trigram index,
3. reciprocal rank fusion of the two rankings,
4. an optional cross-encoder pass.

Dense scores use only vectors whose dimensions and stored
`provider:model_name` key match the query provider. Other chunks remain
eligible for keyword matching. BM25 scores are normalized to higher-is-better
before fusion. A partial rerank response drops candidates without scores;
it never invents zero scores for them. An empty scoring response is an
error. If embedding is unavailable, keyword retrieval remains available.

The database is opened **read-only**, so a running knowledge plugin is
never disturbed. The store is **auto-detected** at the standard location:
if the file exists, the tool is advertised; on machines without the
plugin, the tool is simply absent. `--knowledge-db` or the
`MEMSEARCH_KNOWLEDGE_DB` environment variable override the location.

## Relationship to the plugins

The Codex, Claude Code and DSH plugins are **hooks + skills**: they write
memory automatically at the end of a turn and recall it through a
skill. The MCP server is the **tool surface**: the model decides when to
call it, and it can be combined with anything else the client already
has.

| | plugins (hooks + skills) | `memsearch mcp` |
|---|---|---|
| capture | automatic, on session stop | not handled — the client decides what to store |
| recall | automatic injection / skill call | explicit tool call |
| reach | one agent host | any MCP client |
| extras | — | embedding + rerank backends as tools |

Use both when you can: the plugin keeps the memory up to date, the MCP
server lets the model query it (and the knowledge base) directly.
