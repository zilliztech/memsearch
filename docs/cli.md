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
| `memsearch config` | Initialize, view, and modify configuration |
| `memsearch index` | Scan directories and index markdown files into the vector store |
| `memsearch search` | Semantic search across indexed chunks using natural language |
| `memsearch watch` | Monitor directories and auto-index on file changes |
| `memsearch compact` | Compress indexed chunks into an LLM-generated summary |
| `memsearch expand` | Progressive disclosure L2: show full section around a chunk 🔌 |
| `memsearch transcript` | Progressive disclosure L3: view turns from a JSONL transcript 🔌 |
| `memsearch stats` | Display index statistics (total chunk count) |
| `memsearch reset` | Drop all indexed data from the Milvus collection |

> 🔌 Commands marked with 🔌 are designed for the [platform plugins](platforms/index.md)' progressive disclosure workflow, but work as standalone CLI tools too.

---

## `memsearch config`

Manage memsearch configuration. Configuration is stored in TOML files and follows a layered priority chain:

```
dataclass defaults -> ~/.memsearch/config.toml -> .memsearch.toml -> CLI flags
```

Higher-priority sources override lower-priority ones.

### Subcommands

#### `memsearch config init`

Launch an interactive wizard and write a TOML config file. Global mode walks
through all configuration sections. Project mode writes only allowlisted local
indexing keys to `.memsearch.toml`.

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | `false` | Write allowlisted local indexing keys to `.memsearch.toml` |

```bash
$ memsearch config init
memsearch configuration wizard
Writing to: /home/user/.memsearch/config.toml

-- Milvus --
  Milvus URI [~/.memsearch/milvus.db]:
  Milvus token (empty for none) []:
  Collection name [memsearch_chunks]:

-- Embedding --
  Provider (openai/google/voyage/jina/mistral/ollama/local/onnx) [openai]:
  Model (empty for provider default) []:

-- Chunking --
  Max chunk size (chars) [1500]:
  Overlap lines [2]:

-- Watch --
  Debounce (ms) [1500]:

-- LLM (for memsearch compact) --
  Provider (empty/openai/anthropic/gemini) []:
  Model []:

-- Plugin summarize routing --
  Leave provider empty/native to keep each plugin's current native summarizer.
  Codex automatic summaries enabled [Y/n]:
  Codex summarize provider []:
  Codex summarize model []:

-- Advanced maintenance --
  Disabled by default. Configure provider/model if you enable these tasks.
  Codex project review enabled [y/N]:
  Codex user profile enabled [y/N]:

-- Prompts --
  Leave empty to use built-in defaults.
  Summarize prompt file (for plugin session notes) []:
  Project review prompt file []:
  User profile prompt file []:

Config saved to /home/user/.memsearch/config.toml
```

Create a project-level config:

```bash
$ memsearch config init --project
memsearch configuration wizard
Writing to: .memsearch.toml
Project config is limited to low-risk local indexing keys.
...
```

#### `memsearch config set`

Set a single configuration value by dotted key. Keys follow the `section.field` format.

| Flag | Default | Description |
|------|---------|-------------|
| `KEY` | *(required)* | Dotted config key (e.g., `milvus.uri`) |
| `VALUE` | *(required)* | Value to set |
| `--project` | `false` | Write an allowlisted local indexing key to `.memsearch.toml` instead of global config |

```bash
$ memsearch config set milvus.uri http://localhost:19530
Set milvus.uri = http://localhost:19530 in /home/user/.memsearch/config.toml

$ memsearch config set embedding.batch_size 32 --project
Set embedding.batch_size = 32 in .memsearch.toml

$ memsearch config set chunking.max_chunk_size 2000 --project
Set chunking.max_chunk_size = 2000 in .memsearch.toml
```

Project config is restricted before it is merged. Use `--project` only for
allowlisted local indexing keys such as `milvus.collection`,
`embedding.batch_size`, `chunking.max_chunk_size`, `chunking.overlap_lines`, and
`watch.debounce_ms`. Trusted settings such as provider routing, endpoints, API
keys, prompt files, and plugin automation must go in global config or explicit
CLI flags.

Plugin config keys use `plugins.<platform>.<task>.<field>` and are global:

```bash
$ memsearch config set plugins.codex.summarize.enabled false
Set plugins.codex.summarize.enabled = false in /home/user/.memsearch/config.toml

$ memsearch config set plugins.codex.project_review.enabled true
Set plugins.codex.project_review.enabled = true in /home/user/.memsearch/config.toml

$ memsearch config set plugins.codex.project_review.output_file .memsearch/PROJECT.md
Set plugins.codex.project_review.output_file = .memsearch/PROJECT.md in /home/user/.memsearch/config.toml
```

Supported plugin platforms are `claude-code`, `codex`, `opencode`, and
`openclaw`. Supported plugin tasks are `summarize`, `project_review`,
`user_profile`, and `memory_to_skill`.

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

[llm]
provider = ""
model = ""

[llm.providers.openai]
type = "openai"
model = "gpt-5-mini"
base_url = ""
api_key = "env:OPENAI_API_KEY"

[plugins.claude-code.summarize]
provider = ""
model = ""

[plugins.codex.summarize]
provider = ""
model = ""

[plugins.opencode.summarize]
provider = ""
model = ""

[plugins.openclaw.summarize]
provider = ""
model = ""

[prompts]
compact = ""
summarize = ""
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
| `embedding.batch_size` | int | `0` | Embedding batch size (0 = provider default) |
| `embedding.base_url` | string | `""` | OpenAI-compatible API base URL (empty = SDK default) |
| `embedding.api_key` | string | `""` | API key for embedding provider (supports `env:VAR_NAME` syntax) |
| `chunking.max_chunk_size` | int | `1500` | Maximum chunk size in characters |
| `chunking.overlap_lines` | int | `2` | Number of overlapping lines between adjacent chunks |
| `watch.debounce_ms` | int | `1500` | File watcher debounce delay in milliseconds |
| `compact.llm_provider` | string | `openai` | *(deprecated)* LLM provider for compact — use `llm.provider` instead |
| `compact.llm_model` | string | `""` | *(deprecated)* LLM model — use `llm.model` instead |
| `compact.prompt_file` | string | `""` | *(deprecated)* Prompt file — use `prompts.compact` instead |
| `llm.provider` | string | `""` | LLM provider for `memsearch compact` (empty = compact defaults to openai) |
| `llm.model` | string | `""` | LLM model override for `memsearch compact` |
| `llm.base_url` | string | `""` | OpenAI-compatible API base URL |
| `llm.api_key` | string | `""` | API key (supports `env:VAR_NAME` syntax) |
| `llm.providers.<name>.type` | string | `""` | Named provider type for plugin summarization (`openai`, `openai-compatible`, `anthropic`, `gemini`) |
| `llm.providers.<name>.model` | string | `""` | Default model for a named plugin summarization provider |
| `llm.providers.<name>.base_url` | string | `""` | OpenAI-compatible API base URL for a named provider |
| `llm.providers.<name>.api_key` | string | `""` | API key for a named provider (supports `env:VAR_NAME` syntax) |
| `plugins.claude-code.summarize.provider` | string | `""` | Claude Code summarize provider route (empty/`native` = native summarizer) |
| `plugins.claude-code.summarize.model` | string | `""` | Claude Code native model override, or named provider model override |
| `plugins.codex.summarize.provider` | string | `""` | Codex summarize provider route (empty/`native` = native summarizer) |
| `plugins.codex.summarize.model` | string | `""` | Codex native model override, or named provider model override |
| `plugins.opencode.summarize.provider` | string | `""` | OpenCode summarize provider route (empty/`native` = native summarizer) |
| `plugins.opencode.summarize.model` | string | `""` | OpenCode native model override, or named provider model override |
| `plugins.openclaw.summarize.provider` | string | `""` | OpenClaw summarize provider route (empty/`native` = native summarizer) |
| `plugins.openclaw.summarize.model` | string | `""` | OpenClaw native model override, or named provider model override |
| `prompts.compact` | string | `""` | Custom prompt file for `memsearch compact` |
| `prompts.summarize` | string | `""` | Custom prompt file for plugin session summarization |
| `prompts.project_review` | string | `""` | Custom prompt file for plugin project maintenance |
| `prompts.user_profile` | string | `""` | Custom prompt file for plugin user-profile maintenance |

---

## `memsearch index`

Scan one or more directories (or files) and index all markdown files (`.md`, `.markdown`) into the Milvus vector store. Only new or changed chunks are embedded by default -- unchanged chunks are skipped. Chunks belonging to deleted files under the indexed directory paths are automatically removed from the index.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `PATHS` | | *(required)* | One or more directories or files to index |
| `--provider` | `-p` | `openai` | Embedding provider (`openai`, `google`, `voyage`, `jina`, `mistral`, `ollama`, `local`, `onnx`) |
| `--model` | `-m` | provider default | Override the embedding model name |
| `--base-url` | | *(none)* | OpenAI-compatible API base URL |
| `--api-key` | | *(none)* | API key for the embedding provider |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token (for server or Zilliz Cloud) |
| `--max-chunk-size` | | config value | Override `chunking.max_chunk_size` for this run |
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
- **Stale cleanup.** If a file under an indexed directory path no longer exists on disk, its chunks are automatically deleted from the index during the next `index` run. Explicit file paths are treated as partial updates and do not prune other indexed sources.
- **`--force` re-embeds everything.** Use this when you switch embedding providers or models, since the same content will produce different vectors with a different model.

---

## `memsearch search`

Run a semantic search query against indexed chunks. Uses [hybrid search](https://milvus.io/docs/multi-vector-search.md) (dense vector cosine similarity + [BM25](https://en.wikipedia.org/wiki/Okapi_BM25) full-text) with [RRF](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf) reranking for best results.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `QUERY` | | *(required)* | Natural-language search query |
| `--top-k` | `-k` | `5` | Maximum number of results to return |
| `--provider` | `-p` | `openai` | Embedding provider (must match the provider used at index time) |
| `--model` | `-m` | provider default | Override the embedding model |
| `--base-url` | | *(none)* | OpenAI-compatible API base URL |
| `--api-key` | | *(none)* | API key for the embedding provider |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |
| `--json-output` | `-j` | `false` | Output results as JSON |

### Examples

Basic search:

```bash
$ memsearch search "how to configure Redis caching"

--- Result 1 (score: 0.9919) ---
Source: /home/user/docs/2026-01-15.md
Heading: Redis Configuration
Set REDIS_URL in .env to point to your Redis instance.
Use `cache.set(key, value, ttl=300)` for 5-minute expiry...

--- Result 2 (score: 0.4919) ---
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
    "score": 0.9919
  }
]
```

Use with a different provider (must match the one used for indexing):

```bash
$ memsearch search "database migrations" --provider google
```

### Notes

- **Provider must match.** The search embedding provider and model must match whatever was used during indexing. Mixing providers will return poor results because the vector spaces are incompatible.
- **Hybrid search.** Results are ranked using Reciprocal Rank Fusion (RRF) across both dense (cosine) and sparse (BM25) retrieval, giving you the best of semantic and keyword matching. Scores are normalized to `[0, 1]` where 1.0 means ranked #1 in all retrievers.
- **Content is truncated.** In the default text output, each result's content is truncated to 500 characters. Use `--json-output` to get the full content.

---

## `memsearch watch`

Start a long-running file watcher that monitors directories for markdown file changes. On startup, all existing markdown files are indexed first (dedup ensures no wasted API calls for unchanged content). Then the watcher monitors for changes: when a `.md` or `.markdown` file is created or modified, it is automatically re-indexed. When a file is deleted, its chunks are removed from the store.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `PATHS` | | *(required)* | One or more directories to watch |
| `--debounce-ms` | | `1500` | Debounce delay in milliseconds; multiple rapid changes to the same file within this window are collapsed into a single re-index |
| `--provider` | `-p` | `openai` | Embedding provider |
| `--model` | `-m` | provider default | Override the embedding model |
| `--base-url` | | *(none)* | OpenAI-compatible API base URL |
| `--api-key` | | *(none)* | API key for the embedding provider |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |
| `--max-chunk-size` | | config value | Override `chunking.max_chunk_size` for this run |

### Examples

Watch a single directory:

```bash
$ memsearch watch ./memory/
Indexed 8 chunks.
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

- **Initial index on startup.** The watcher indexes all existing files before it starts monitoring. Content-hash dedup means unchanged files are skipped with zero API calls — only genuinely new or modified content is embedded.
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
| `--base-url` | | *(none)* | OpenAI-compatible API base URL |
| `--api-key` | | *(none)* | API key for the embedding provider |
| `--collection` | `-c` | `memsearch_chunks` | Milvus collection name |
| `--milvus-uri` | | `~/.memsearch/milvus.db` | Milvus connection URI |
| `--milvus-token` | | *(none)* | Milvus auth token |

### Default LLM Models

| Provider | Default Model |
|----------|--------------|
| `openai` | `gpt-5-mini` |
| `anthropic` | `claude-sonnet-4-6` |
| `gemini` | `gemini-3-flash-preview` |

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

Relative and `~` paths are automatically resolved to the absolute form used at index time. If no chunks match, memsearch prints the resolved source path to help debug the filter.

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

> 🔌 **Plugin command.** This command is part of the [platform plugins](platforms/index.md)' three-level progressive disclosure workflow (`search` → `expand` → `transcript`), but works as a standalone CLI tool for any memsearch index.

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
| `--base-url` | | *(none)* | OpenAI-compatible API base URL |
| `--api-key` | | *(none)* | API key for the embedding provider |
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

> 🔌 **Plugin command.** This command is part of the [platform plugins](platforms/index.md)' three-level progressive disclosure workflow (`search` → `expand` → `transcript`), but works as a standalone CLI tool for any JSONL transcript.

Parse a session transcript and display its conversation turns **with the tool calls** — the exact commands and their output. Auto-detects Claude Code, Codex (rollout), and OpenClaw JSONL formats. This is "progressive disclosure level 3" -- drilling from a memory chunk down to the original conversation, where the detail the journal summary drops (precise commands, flags, paths) still lives.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `JSONL_PATH` | | *(required)* | Path to the JSONL transcript file |
| `--turn` | `-t` | *(show all)* | Target turn UUID (prefix match supported) |
| `--context` | `-c` | `3` | Number of turns to show before and after the target turn |
| `--json-output` | `-j` | `false` | Output as JSON |

### Examples

View a transcript, including the commands that were run:

```bash
$ memsearch transcript ./transcripts/session-abc123.jsonl
### User
Add TTL support to the cache

### Assistant
I'll add TTL and run the tests.
- $ [Edit] src/cache.py
- $ [Bash] pytest tests/cache_test.py -x
  → 5 passed in 0.4s
```

Show context around a specific turn (UUID prefix match):

```bash
$ memsearch transcript ./transcripts/session-abc123.jsonl --turn d4e5f6 --context 2
```

Output as JSON (each turn has its role, text, and structured tool calls):

```bash
$ memsearch transcript ./transcripts/session-abc123.jsonl --json-output
[
  {
    "role": "assistant",
    "uuid": "a1b2c3d4-...",
    "text": "I'll add TTL and run the tests.",
    "tools": [
      {"name": "Bash", "command": "pytest tests/cache_test.py -x", "output": "5 passed in 0.4s"}
    ]
  }
]
```

### Notes

- **Tool calls are the point.** Unlike the journal summaries, this includes the exact command for each tool call and (truncated) output — which is what makes a distilled skill accurate. See [Skills from Memory](home/skills-from-memory.md).
- **UUID prefix matching.** The first 6-8 characters of a turn id are usually enough; some formats (e.g. Codex rollouts) have no per-turn id, in which case all turns are returned.
- **Unknown formats** exit with a non-zero status and a message, so a caller can fall back to reading the file directly.
- **Three-level progressive disclosure workflow:** `search` (L1: chunk snippet) -> `expand` (L2: full section) -> `transcript` (L3: original conversation).

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

memsearch reads API keys from environment variables by default. You can also configure them in TOML config files using the `env:VAR_NAME` reference syntax or the `embedding.api_key` / `embedding.base_url` fields. See [Configuration](getting-started.md#configuration) for details.

### API Keys

| Variable | Required By | Description |
|----------|-------------|-------------|
| `OPENAI_API_KEY` | `openai` embedding provider, `openai` LLM compact provider | OpenAI API key |
| `OPENAI_BASE_URL` | *(optional)* | Override the OpenAI API base URL (for proxies or compatible APIs) |
| `GOOGLE_API_KEY` | `google` embedding provider, `gemini` LLM compact provider | Google AI API key |
| `VOYAGE_API_KEY` | `voyage` embedding provider | Voyage AI API key |
| `JINA_API_KEY` | `jina` embedding provider | Jina AI API key |
| `MISTRAL_API_KEY` | `mistral` embedding provider | Mistral AI API key |
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
| `jina` | `pip install "memsearch[jina]"` | `jina-embeddings-v4` | 2048 | `JINA_API_KEY` |
| `mistral` | `pip install "memsearch[mistral]"` | `mistral-embed` | 1024 | `MISTRAL_API_KEY` |
| `ollama` | `pip install "memsearch[ollama]"` | `nomic-embed-text` | 768 | *(none, local)* |
| `local` | `pip install "memsearch[local]"` | `all-MiniLM-L6-v2` | 384 | *(none, local)* |
| `onnx` | `pip install "memsearch[onnx]"` | `gpahal/bge-m3-onnx-int8` | 1024 | *(none, local)* |

Install all optional providers at once:

```bash
$ pip install "memsearch[all]"
```
