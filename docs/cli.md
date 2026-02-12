# CLI Reference

memsearch provides a command-line interface for indexing, searching, and managing semantic memory over markdown knowledge bases.

```bash
$ memsearch --version
memsearch, version 0.1.3

$ memsearch --help
Usage: memsearch [OPTIONS] COMMAND [ARGS]...

  memsearch — semantic memory search for markdown knowledge bases.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  compact     Compress stored memories into a summary.
  config      Manage memsearch configuration.
  expand      Expand a memory chunk to show full context.
  index       Index markdown files from PATHS.
  reset       Drop all indexed data.
  search      Search indexed memory for QUERY.
  stats       Show statistics about the index.
  transcript  View original conversation turns from a JSONL transcript.
  watch       Watch PATHS for markdown changes and auto-index.
```

## Command Summary

| Command | Description |
|---------|-------------|
| `memsearch index` | Scan directories and index markdown files into the vector store |
| `memsearch search` | Semantic search across indexed chunks using natural language |
| `memsearch watch` | Monitor directories and auto-index on file changes |
| `memsearch compact` | Compress indexed chunks into an LLM-generated summary |
| `memsearch expand` | Progressive disclosure L2: show full section around a chunk 🔌 |
| `memsearch transcript` | Progressive disclosure L3: view turns from a JSONL transcript 🔌 |
| `memsearch config` | Initialize, view, and modify configuration |
| `memsearch stats` | Display index statistics (total chunk count) |
| `memsearch reset` | Drop all indexed data from the Milvus collection |

> 🔌 Commands marked with 🔌 are designed for the [Claude Code plugin](../ccplugin/README.md)'s progressive disclosure workflow, but work as standalone CLI tools too.

---

## `memsearch index`

Scan one or more directories (or files) and index all markdown files (`.md`, `.markdown`) into the Milvus vector store. Only new or changed chunks are embedded by default -- unchanged chunks are skipped. Chunks belonging to deleted files are automatically removed from the index.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `PATHS` | | *(required)* | One or more directories or files to index |
| `--provider` | `-p` | `openai` | Embedding provider (`openai`, `google`, `voyage`, `ollama`, `local`) |
| `--model` | `-m` | provider default | Override the embedding model name |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token (for server or Zilliz Cloud) |
| `--force` | | `false` | Re-embed and re-index all chunks, even if unchanged |

### Examples

Index a single directory:

```bash
$ memsearch index ./memory/
Indexed 42 chunks.
```

Index multiple directories with a specific embedding provider:

```bash
$ memsearch index ./memory/ ./notes/ --provider google
Indexed 87 chunks.
```

Force re-index everything (ignores the content-hash dedup check):

```bash
$ memsearch index ./memory/ --force
Indexed 42 chunks.
```

Connect to a remote Milvus server instead of the default local file:

```bash
$ memsearch index ./memory/ --milvus-uri http://localhost:19530
Indexed 42 chunks.
```

Use a custom embedding model:

```bash
$ memsearch index ./memory/ --provider openai --model text-embedding-3-large
Indexed 42 chunks.
```

### Notes

- **Incremental by default.** Each chunk is identified by a composite hash of its source file, line range, content hash, and embedding model. Only chunks with new IDs are embedded and stored.
- **Stale cleanup.** If a file that was previously indexed no longer exists on disk, its chunks are automatically deleted from the index during the next `index` run.
- **`--force` re-embeds everything.** Use this when you switch embedding providers or models, since the same content will produce different vectors with a different model.

---

## `memsearch search`

Run a semantic search query against indexed chunks. Uses hybrid search (dense vector cosine similarity + BM25 full-text) with RRF reranking for best results.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `QUERY` | | *(required)* | Natural-language search query |
| `--top-k` | `-k` | `5` | Maximum number of results to return |
| `--provider` | `-p` | `openai` | Embedding provider (must match the provider used at index time) |
| `--model` | `-m` | provider default | Override the embedding model |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |
| `--json-output` | `-j` | `false` | Output results as JSON |

### Examples

Basic search:

```bash
$ memsearch search "how to configure Redis caching"

--- Result 1 (score: 0.0328) ---
Source: /home/user/docs/2026-01-15.md
Heading: Redis Configuration
Set REDIS_URL in .env to point to your Redis instance.
Use `cache.set(key, value, ttl=300)` for 5-minute expiry...

--- Result 2 (score: 0.0326) ---
Source: /home/user/docs/architecture.md
Heading: Caching Layer
We use Redis as the primary caching backend...
```

Return more results:

```bash
$ memsearch search "authentication flow" --top-k 10
```

Output as JSON (useful for piping to `jq` or other tools):

```bash
$ memsearch search "error handling" --json-output
[
  {
    "content": "All API endpoints should return structured error...",
    "source": "/home/user/docs/api-design.md",
    "heading": "Error Handling",
    "chunk_hash": "a1b2c3d4e5f6...",
    "heading_level": 2,
    "start_line": 45,
    "end_line": 62,
    "score": 0.0330
  }
]
```

Use with a different provider (must match the one used for indexing):

```bash
$ memsearch search "database migrations" --provider google
```

### Notes

- **Provider must match.** The search embedding provider and model must match whatever was used during indexing. Mixing providers will return poor results because the vector spaces are incompatible.
- **Hybrid search.** Results are ranked using Reciprocal Rank Fusion (RRF) across both dense (cosine) and sparse (BM25) retrieval, giving you the best of semantic and keyword matching.
- **Content is truncated.** In the default text output, each result's content is truncated to 500 characters. Use `--json-output` to get the full content.

---

## `memsearch watch`

Start a long-running file watcher that monitors directories for markdown file changes. When a `.md` or `.markdown` file is created or modified, it is automatically re-indexed. When a file is deleted, its chunks are removed from the store.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `PATHS` | | *(required)* | One or more directories to watch |
| `--debounce-ms` | | `1500` | Debounce delay in milliseconds; multiple rapid changes to the same file within this window are collapsed into a single re-index |
| `--provider` | `-p` | `openai` | Embedding provider |
| `--model` | `-m` | provider default | Override the embedding model |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |

### Examples

Watch a single directory:

```bash
$ memsearch watch ./memory/
Watching 1 path(s) for changes... (Ctrl+C to stop)
Indexed 3 chunks from /home/user/docs/2026-02-11.md
Removed chunks for /home/user/docs/old-draft.md
^C
Stopping watcher.
```

Watch multiple directories with a longer debounce:

```bash
$ memsearch watch ./memory/ ./notes/ --debounce-ms 3000
Watching 2 path(s) for changes... (Ctrl+C to stop)
```

### Notes

- **Debounce.** Editors that write files in multiple steps (e.g., write temp file, then rename) can trigger several events in quick succession. The debounce window collapses these into one re-index operation.
- **Recursive.** The watcher monitors all subdirectories recursively.
- **Singleton behavior.** Only one watcher process should run per directory set. Running multiple watchers on the same paths will cause duplicate indexing work (though dedup by content hash means the index stays consistent).
- **Stop with Ctrl+C.** The watcher runs until you interrupt it.

---

## `memsearch compact`

Use an LLM to compress all indexed chunks (or a subset) into a condensed markdown summary. The summary is appended to a daily log file at `memory/YYYY-MM-DD.md` inside the first configured path, keeping markdown as the single source of truth.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--source` | `-s` | *(all chunks)* | Only compact chunks from this specific source file |
| `--output-dir` | `-o` | first configured path | Directory to write the compact summary into |
| `--llm-provider` | | `openai` | LLM backend for summarization (`openai`, `anthropic`, `gemini`) |
| `--llm-model` | | provider default | Override the LLM model |
| `--prompt` | | built-in template | Custom prompt template string (must contain `{chunks}` placeholder) |
| `--prompt-file` | | *(none)* | Read the prompt template from a file instead |
| `--provider` | `-p` | `openai` | Embedding provider (used to access the index) |
| `--model` | `-m` | provider default | Override the embedding model |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |

### Default LLM Models

| Provider | Default Model |
|----------|--------------|
| `openai` | `gpt-4o-mini` |
| `anthropic` | `claude-sonnet-4-5-20250929` |
| `gemini` | `gemini-2.0-flash` |

### Examples

Compact all chunks using the default LLM (OpenAI):

```bash
$ memsearch compact
Compact complete. Summary:

## Key Decisions
- Use Redis for session caching with 5-minute TTL
- All API errors return structured JSON responses
...
```

Compact only chunks from a specific source file:

```bash
$ memsearch compact --source ./memory/old-notes.md
Compact complete. Summary:

## Old Notes Summary
- Initial architecture decisions from January meeting...
```

Use Anthropic Claude for summarization:

```bash
$ memsearch compact --llm-provider anthropic
```

Use a custom prompt template:

```bash
$ memsearch compact --prompt "Summarize these notes into action items:\n{chunks}"
```

Use a prompt file for complex templates:

```bash
$ memsearch compact --prompt-file ./prompts/compress.txt
```

### Notes

- **Output location.** The summary is appended to `<first-path>/memory/YYYY-MM-DD.md`. This file is then automatically eligible for future indexing.
- **The `{chunks}` placeholder is required.** Whether using `--prompt` or `--prompt-file`, the template must contain `{chunks}` which will be replaced with the concatenated chunk contents.
- **API key required.** The chosen LLM provider requires its corresponding API key in the environment (see [Environment Variables](#environment-variables)).

---

## `memsearch expand`

> 🔌 **Claude Code plugin command.** This command is part of the [ccplugin](../ccplugin/README.md)'s three-level progressive disclosure workflow (`search` → `expand` → `transcript`), but works as a standalone CLI tool for any memsearch index.

Look up a chunk by its hash in the index and return the surrounding context from the original source markdown file. This is "progressive disclosure level 2" -- when a search result snippet is not enough, expand it to see the full heading section.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `CHUNK_HASH` | | *(required)* | The chunk hash (primary key) to look up |
| `--section/--no-section` | | `--section` | Show the full heading section (default behavior) |
| `--lines` | `-n` | *(full section)* | Instead of the full section, show N lines before and after the chunk |
| `--json-output` | `-j` | `false` | Output as JSON |
| `--provider` | `-p` | `openai` | Embedding provider |
| `--model` | `-m` | provider default | Override the embedding model |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |

### Examples

Expand a chunk to see its full heading section:

```bash
$ memsearch expand a1b2c3d4e5f6
Source: /home/user/docs/architecture.md (lines 10-35)
Heading: Caching Layer

## Caching Layer

We use Redis as the primary caching backend. All cache keys
follow the pattern `service:entity:id`.

### Configuration
Set REDIS_URL in .env to point to your Redis instance.
Use `cache.set(key, value, ttl=300)` for 5-minute expiry.
...
```

Show only 5 lines of context around the chunk:

```bash
$ memsearch expand a1b2c3d4e5f6 --lines 5
Source: /home/user/docs/architecture.md (lines 18-28)
Heading: Caching Layer

Set REDIS_URL in .env to point to your Redis instance.
Use `cache.set(key, value, ttl=300)` for 5-minute expiry.
...
```

Get JSON output (includes anchor metadata if present):

```bash
$ memsearch expand a1b2c3d4e5f6 --json-output
{
  "chunk_hash": "a1b2c3d4e5f6",
  "source": "/home/user/docs/architecture.md",
  "heading": "Caching Layer",
  "start_line": 10,
  "end_line": 35,
  "content": "## Caching Layer\n\nWe use Redis as the primary..."
}
```

### Notes

- **Source file must exist.** The `expand` command reads the original markdown file from disk. If the source file has been moved or deleted, the command will fail with an error.
- **Anchor parsing.** If the expanded text contains an HTML anchor comment in the format `<!-- session:ID turn:ID transcript:PATH -->`, the command parses it and displays the session, turn, and transcript file information. This connects memory chunks to their original conversation transcripts.
- **Workflow: search then expand.** A typical workflow is to `search` first, note the `chunk_hash` from a result, then `expand` it to see more context.

---

## `memsearch transcript`

> 🔌 **Claude Code plugin command.** This command is part of the [ccplugin](../ccplugin/README.md)'s three-level progressive disclosure workflow (`search` → `expand` → `transcript`), but works as a standalone CLI tool for any JSONL transcript.

Parse a JSONL transcript file (e.g., from Claude Code) and display conversation turns. This is "progressive disclosure level 3" -- drill all the way down from a memory chunk to the original conversation that generated it.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `JSONL_PATH` | | *(required)* | Path to the JSONL transcript file |
| `--turn` | `-t` | *(show all)* | Target turn UUID (prefix match supported) |
| `--context` | `-c` | `3` | Number of turns to show before and after the target turn |
| `--json-output` | `-j` | `false` | Output as JSON |

### Examples

List all turns in a transcript:

```bash
$ memsearch transcript ./transcripts/session-abc123.jsonl
All turns (12):

  a1b2c3d4e5f6  14:23:05  Show me the Redis configuration code
  d4e5f6a1b2c3  14:23:42  Can you add TTL support to the cache?
  f6a1b2c3d4e5  14:25:10  Write tests for the cache module
  ...
```

Show context around a specific turn (prefix match on UUID):

```bash
$ memsearch transcript ./transcripts/session-abc123.jsonl --turn d4e5f6
Showing 5 turns around d4e5f6a1b2c3:

[14:22:30] a1b2c3d4
Show me the Redis configuration code

**Assistant**: Here is the current Redis configuration...

>>> [14:23:42] d4e5f6a1
Can you add TTL support to the cache?

**Assistant**: I'll add TTL support. Here are the changes...
  Tools: Edit(/src/cache.py), Bash(pytest tests/)

[14:25:10] f6a1b2c3
Write tests for the cache module
```

Output as JSON:

```bash
$ memsearch transcript ./transcripts/session-abc123.jsonl --turn d4e5f6 --json-output
[
  {
    "uuid": "a1b2c3d4-...",
    "timestamp": "2026-02-10T14:22:30Z",
    "content": "Show me the Redis configuration code\n\n**Assistant**: ...",
    "tool_calls": []
  }
]
```

### Notes

- **UUID prefix matching.** You do not need to provide the full UUID. The first 6-8 characters are usually enough to uniquely identify a turn.
- **The `>>>` marker** in text output highlights the target turn when using `--turn`.
- **Three-level progressive disclosure workflow:** `search` (L1: chunk snippet) -> `expand` (L2: full section) -> `transcript` (L3: original conversation).

---

## `memsearch config`

Manage memsearch configuration. Configuration is stored in TOML files and follows a layered priority chain:

```
dataclass defaults -> ~/.memsearch/config.toml -> .memsearch.toml -> CLI flags
```

Higher-priority sources override lower-priority ones.

### Subcommands

#### `memsearch config init`

Launch an interactive wizard that walks through all configuration sections and writes a TOML config file.

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | `false` | Write to `.memsearch.toml` (project-level) instead of the global config |

```bash
$ memsearch config init
memsearch configuration wizard
Writing to: /home/user/.memsearch/config.toml

-- Milvus --
  Milvus URI [~/.memsearch/milvus.db]:
  Milvus token (empty for none) []:
  Collection name [memsearch_chunks]:

-- Embedding --
  Provider (openai/google/voyage/ollama/local) [openai]:
  Model (empty for provider default) []:

-- Chunking --
  Max chunk size (chars) [1500]:
  Overlap lines [2]:

-- Watch --
  Debounce (ms) [1500]:

-- Compact --
  LLM provider [openai]:
  LLM model (empty for default) []:
  Prompt file path (empty for built-in) []:

Config saved to /home/user/.memsearch/config.toml
```

Create a project-level config:

```bash
$ memsearch config init --project
memsearch configuration wizard
Writing to: .memsearch.toml
...
```

#### `memsearch config set`

Set a single configuration value by dotted key. Keys follow the `section.field` format.

| Flag | Default | Description |
|------|---------|-------------|
| `KEY` | *(required)* | Dotted config key (e.g., `milvus.uri`) |
| `VALUE` | *(required)* | Value to set |
| `--project` | `false` | Write to `.memsearch.toml` instead of global config |

```bash
$ memsearch config set milvus.uri http://localhost:19530
Set milvus.uri = http://localhost:19530 in /home/user/.memsearch/config.toml

$ memsearch config set embedding.provider google --project
Set embedding.provider = google in .memsearch.toml

$ memsearch config set chunking.max_chunk_size 2000
Set chunking.max_chunk_size = 2000 in /home/user/.memsearch/config.toml
```

#### `memsearch config get`

Read a single resolved configuration value (merged from all sources).

```bash
$ memsearch config get milvus.uri
http://localhost:19530

$ memsearch config get embedding.provider
openai

$ memsearch config get chunking.max_chunk_size
1500
```

#### `memsearch config list`

Display configuration in TOML format.

| Flag | Default | Description |
|------|---------|-------------|
| `--resolved` | *(default)* | Show the fully merged configuration from all sources |
| `--global` | | Show only the global config file (`~/.memsearch/config.toml`) |
| `--project` | | Show only the project config file (`.memsearch.toml`) |

```bash
$ memsearch config list --resolved
# Resolved (all sources merged)

[milvus]
uri = "~/.memsearch/milvus.db"
token = ""
collection = "memsearch_chunks"

[embedding]
provider = "openai"
model = ""

[chunking]
max_chunk_size = 1500
overlap_lines = 2

[watch]
debounce_ms = 1500

[compact]
llm_provider = "openai"
llm_model = ""
prompt_file = ""
```

```bash
$ memsearch config list --global
# Global (/home/user/.memsearch/config.toml)

[milvus]
uri = "http://localhost:19530"

[embedding]
provider = "openai"
```

### Available Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `milvus.uri` | string | `~/.memsearch/milvus.db` | Milvus connection URI |
| `milvus.token` | string | `""` | Auth token for Milvus Server / Zilliz Cloud |
| `milvus.collection` | string | `memsearch_chunks` | Collection name |
| `embedding.provider` | string | `openai` | Embedding provider name |
| `embedding.model` | string | `""` | Override embedding model (empty = provider default) |
| `chunking.max_chunk_size` | int | `1500` | Maximum chunk size in characters |
| `chunking.overlap_lines` | int | `2` | Number of overlapping lines between adjacent chunks |
| `watch.debounce_ms` | int | `1500` | File watcher debounce delay in milliseconds |
| `compact.llm_provider` | string | `openai` | LLM provider for compact summarization |
| `compact.llm_model` | string | `""` | Override LLM model (empty = provider default) |
| `compact.prompt_file` | string | `""` | Path to a custom prompt template file |

---

## `memsearch stats`

Show statistics about the current index, including the total number of stored chunks.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |

### Examples

```bash
$ memsearch stats
Total indexed chunks: 142
```

Check stats for a specific collection on a remote server:

```bash
$ memsearch stats --milvus-uri http://localhost:19530 --collection my_project
Total indexed chunks: 87
```

### Notes

- **Stats may lag on remote Milvus Server.** The `get_collection_stats()` API on a remote Milvus Server may return stale counts immediately after an upsert. Stats are updated after segment flush and compaction. Search results are always up to date.

---

## `memsearch reset`

Drop the entire Milvus collection, permanently deleting all indexed chunks. A confirmation prompt is shown before proceeding.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |
| `--yes` | `-y` | | Skip the confirmation prompt |

### Examples

```bash
$ memsearch reset
This will delete all indexed data. Continue? [y/N]: y
Dropped collection.
```

Skip the confirmation prompt (useful in scripts):

```bash
$ memsearch reset --yes
Dropped collection.
```

Reset a specific collection on a remote server:

```bash
$ memsearch reset --milvus-uri http://localhost:19530 --collection old_project --yes
Dropped collection.
```

### Notes

- **This is destructive and irreversible.** All indexed data will be lost. Your original markdown files are not affected -- you can always re-index them with `memsearch index`.
- **Only drops the collection, not the database.** If you are using Milvus Lite (a local `.db` file), the file itself remains; only the collection inside it is removed.

---

## Environment Variables

memsearch reads API keys from environment variables. These are required by the corresponding embedding and LLM provider SDKs and are **not** stored in memsearch config files.

### API Keys

| Variable | Required By | Description |
|----------|-------------|-------------|
| `OPENAI_API_KEY` | `openai` embedding provider, `openai` LLM compact provider | OpenAI API key |
| `OPENAI_BASE_URL` | *(optional)* | Override the OpenAI API base URL (for proxies or compatible APIs) |
| `GOOGLE_API_KEY` | `google` embedding provider, `gemini` LLM compact provider | Google AI API key |
| `VOYAGE_API_KEY` | `voyage` embedding provider | Voyage AI API key |
| `ANTHROPIC_API_KEY` | `anthropic` LLM compact provider | Anthropic API key |
| `OLLAMA_HOST` | `ollama` embedding provider *(optional)* | Ollama server URL (default: `http://localhost:11434`) |

All memsearch settings (Milvus URI, embedding provider, chunking parameters, etc.) are configured via TOML config files or CLI flags -- see [Configuration](getting-started.md#configuration) for details.

### Examples

```bash
# Set API key and run a search
$ export OPENAI_API_KEY=sk-...
$ memsearch search "database schema"

# Use Google for embedding, Anthropic for compact
$ export GOOGLE_API_KEY=AIza...
$ memsearch index ./memory/ --provider google
$ memsearch compact --llm-provider anthropic
```

### Embedding Provider Reference

| Provider | Install | Default Model | Dimension | API Key Variable |
|----------|---------|---------------|-----------|-----------------|
| `openai` | included by default | `text-embedding-3-small` | 1536 | `OPENAI_API_KEY` |
| `google` | `pip install "memsearch[google]"` | `gemini-embedding-001` | 768 | `GOOGLE_API_KEY` |
| `voyage` | `pip install "memsearch[voyage]"` | `voyage-3-lite` | 512 | `VOYAGE_API_KEY` |
| `ollama` | `pip install "memsearch[ollama]"` | `nomic-embed-text` | 768 | *(none, local)* |
| `local` | `pip install "memsearch[local]"` | `all-MiniLM-L6-v2` | 384 | *(none, local)* |

Install all optional providers at once:

```bash
$ pip install "memsearch[all]"
```
