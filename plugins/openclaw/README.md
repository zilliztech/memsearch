# memsearch — OpenClaw Plugin

Automatic persistent memory for [OpenClaw](https://github.com/openclaw/openclaw). Successful conversation turns are summarized and indexed for later recall. Transcript access depends on the host's storage and authorization capabilities.

## Prerequisites

- [OpenClaw](https://github.com/openclaw/openclaw) >= 2026.3.11, matching the package's plugin API and peer dependency declarations
- Python 3.10+

Tool, hook and CLI discovery have been checked on 2026.3.11, 2026.3.22 and 2026.10.5. Discovery does not establish successful model-driven capture or recall. See the [current compatibility report](https://github.com/zilliztech/memsearch/blob/main/plugins/openclaw/reports/compatibility.md) for validation scope and transcript limitations. The retained `plugin-inspector-*` reports describe a historical 0.3.19 snapshot.

## Install

### From ClawHub (recommended)

```bash
# 1. Install memsearch
uv tool install "memsearch[onnx]"

# 2. Install the plugin from ClawHub
openclaw plugins install --force clawhub:memsearch

# 3. Allow memsearch to read conversation turns and inject recall context
openclaw config set plugins.entries.memsearch.hooks.allowConversationAccess true
openclaw config set plugins.entries.memsearch.hooks.allowPromptInjection true

# 4. Restart the gateway
openclaw gateway restart
```

### From Source (development)

```bash
# 1. Install memsearch
uv tool install "memsearch[onnx]"

# 2. Clone the repo and install the plugin
git clone https://github.com/zilliztech/memsearch.git
cd memsearch
openclaw plugins install --link --force ./plugins/openclaw

# 3. Allow memsearch to read conversation turns and inject recall context
openclaw config set plugins.entries.memsearch.hooks.allowConversationAccess true
openclaw config set plugins.entries.memsearch.hooks.allowPromptInjection true

# 4. Restart the gateway
openclaw gateway restart
```

## Usage

Start a TUI session as normal:

```bash
openclaw tui
```

### What happens automatically

| When | What |
|------|------|
| Agent starts | Recent memories injected as context |
| Each turn ends | Conversation summarized (bullet-points) and saved to daily `.md` |
| LLM needs history | Calls `memory_search` / `memory_get` / `memory_transcript` tools |

### Recall memories

Two ways to trigger:

```
/memory-recall what was the caching strategy we chose?
```
Or just ask naturally — the LLM auto-invokes memory tools when it senses the question needs history:
```
We discussed caching strategies before, what did we decide?
```

### Three-layer progressive recall

The plugin registers three tools the LLM uses progressively:

1. **`memory_search`** — Semantic search across past memories. Always starts here.
2. **`memory_get`** — Expand a chunk to see the full markdown section with context.
3. **`memory_transcript`** — Read dialogue using the exact `transcript` reference emitted by capture. Older hosts use JSONL references; newer hosts use the public session transcript SDK for SQLite.

The LLM decides how deep to go based on the question — simple recall uses only L1, detailed questions go to L2/L3.

On SDK hosts, explicit L3 reads follow the host's configured `tools.sessions.visibility` policy. The default `all` and `agent` permit historical sessions within the calling profile/store and agent; `self` restricts reads to the current key, and `tree` uses trusted host ownership metadata. The exact historical key and session ID must still match. This explicit history permission does not require a memory audience and does not authorize automatic recall or capture into other audiences.

The plugin conservatively rejects role-controlled cross-session reads, draft/incognito or unconfirmed target metadata, sandboxed/workspace-confined callers, and unsupported auxiliary/global read scopes. Scoped-grant-only access is not supported. On SDK hosts, use the emitted `openclaw-session:` reference; legacy paths cannot bypass policy checks. The source candidate passed real TUI capture, automatic API summarization/indexing, and fresh-session three-tool recall on OpenClaw 2026.10.5. See the [compatibility report](reports/compatibility.md) for the tested configuration and authorization limits.

On older hosts without the SDK, standard `<sessionId>.jsonl` files remain supported inside the current agent's host-resolved session store. Paths outside that store, including escaping symlinks, are rejected. Restricted `self`/`tree` policies and role-controlled configurations reject cross-session legacy paths whose target metadata cannot be confirmed. Automatic capture omits an anchor when the standard file is absent; topic suffixes and custom `sessionFile` paths are not guessed.

The modern reader returns user/assistant text from the last user turn, capped at 32,000 characters. It reads the whole visible transcript first, so memory consumption scales with transcript size. Capture skips failed turns and restricted conversation audiences, and binds each summary and index operation to its original hook workspace.

### Multi-agent isolation

Each OpenClaw agent stores memory independently under its own workspace:

```
~/.openclaw/workspace/.memsearch/memory/          ← main agent
~/.openclaw/workspace-work/.memsearch/memory/      ← work agent
```

Collection names are derived from the workspace path, so agents with different workspaces have isolated memories. When an agent's workspace points to a project directory used by other platforms, memories are automatically shared across platforms.

Hook context supplies the capture workspace and session identity even before the first tool call. Named profiles use OpenClaw's resolved state and session-store paths. Sharing a memory directory does not grant transcript access to another profile or agent.

### Shared memory across projects

Set `MEMSEARCH_DIR` to a fixed path to share a single memory store across all agents and projects:

```bash
export MEMSEARCH_DIR=~/.memsearch
openclaw tui
```

When `MEMSEARCH_DIR` is set:
- All agents write memories to that directory regardless of their workspace path.
- The collection name is derived from `MEMSEARCH_DIR` instead of the workspace path, so all agents share the same index.

## Configuration

ONNX embeddings run locally without an API key. Summarization uses the configured OpenClaw model or a named MemSearch API provider.

Optional settings via `openclaw plugins config memsearch`:

| Setting | Default | Description |
|---------|---------|-------------|
| `provider` | `onnx` | Embedding provider (onnx, openai, google, voyage, jina, mistral, ollama) |
| `autoCapture` | `true` | Auto-capture conversation summaries after each turn |
| `autoRecall` | `true` | Auto-inject recent memories at agent start |

To override only the OpenClaw native capture summarization model:

```bash
memsearch config set plugins.openclaw.summarize.model qwen3-coder
```

For API summaries, make `OPENAI_API_KEY` available to the OpenClaw process and configure the MemSearch home used by that process. The following configuration passed real capture and recall with `gpt-5.6-luna`:

```bash
memsearch config set llm.providers.openai.type openai
memsearch config set llm.providers.openai.base_url https://api.openai.com/v1
memsearch config set llm.providers.openai.api_key env:OPENAI_API_KEY
memsearch config set plugins.openclaw.summarize.provider openai
memsearch config set plugins.openclaw.summarize.model gpt-5.6-luna
```

This stores an environment reference for the key and sends summaries through MemSearch's OpenAI provider. Embeddings remain on the configured provider, including ONNX. The OpenClaw inference model and its authentication are configured separately.

An empty or `native` summary provider uses `openclaw agent --local` with the configured summary model, or the OpenClaw agent model when no summary model is set. It does not fall back to `llm.model`. On OpenClaw 2026.10.5, a live local TUI can hold the state-database ownership lock and prevent that native summary child from starting. Capture then saves the truncated raw-turn fallback. Use the API summary configuration above for the verified local-TUI path; native summarization has not passed this E2E.

## Memory files

Each agent's memory is stored as plain markdown:

```markdown
# 2026-03-25

## Session 14:47

### 14:47
<!-- session:UUID transcript:/path/to/openclaw-state/agents/main/sessions/UUID.jsonl -->
- User asked about the memsearch architecture.
- OpenClaw explained core components: chunker, scanner, embedder, MilvusStore.
```

This example uses a legacy JSONL anchor. SDK hosts emit an `openclaw-session:` reference with the exact session identity and host-resolved store selector. The non-secret session selector uses the `sessionKey` query field so it survives the host's model-facing credential redaction. Pass that reference unchanged to `memory_transcript`; it is a locator, not an authorization grant.

These files are human-readable, editable, and version-controllable. Milvus is a derived index that can be rebuilt anytime.

## Uninstall

```bash
openclaw plugins uninstall memsearch
openclaw gateway restart
```

Uninstalling the plugin does not delete memory files in `.memsearch/memory/`.
