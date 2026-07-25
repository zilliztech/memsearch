# Memory Tools

The plugin registers three tools with pi. They form a progressive disclosure
chain: each layer is more expensive than the last, so stop as soon as you have
enough.

| Layer | Tool | Returns | Typical cost |
|-------|------|---------|--------------|
| L1 | `memory_search` | Matching chunks across all past sessions | One embedding + hybrid search |
| L2 | `memory_get` | The full markdown section for one chunk | One key lookup |
| L3 | `memory_transcript` | The original conversation behind that section | One file parse |

---

## L1 — `memory_search`

Semantic search over every captured memory in the project's collection, powered
by Milvus hybrid search: dense vectors for meaning, BM25 for exact terms, fused
with RRF.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `query` | Yes | What to look for, phrased as intent rather than keywords |
| `top_k` | No | Number of results (default 5) |

Scores are normalized to `[0, 1]`. Results are truncated -- expand before
relying on a hit.

---

## L2 — `memory_get`

Expands one search result into its complete markdown section, including
surrounding context in the same journal entry.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `chunk_hash` | Yes | The `chunk_hash` from a `memory_search` result |

An expanded section carries the anchor comment recorded at capture time:

```markdown
<!-- session:019f98ab-… turn:156b1bd4 transcript:/Users/you/.pi/agent/sessions/…jsonl -->
```

That anchor is the input to L3.

---

## L3 — `memory_transcript`

Reads the original exchange out of pi's session file. Use it when the summary is
too lossy -- most often when you need the exact command, flag, or path that was
actually run, rather than a description of it.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `transcript_path` | Yes | The `transcript:` path from the anchor |
| `turn_id` | No | The `turn:` id from the anchor |
| `context` | No | Turns before and after the target (default 3) |
| `limit` | No | Max turns when no `turn_id` is given (default 20) |

With a `turn_id`, the target turn is marked:

```
[User] 09:46
一句话说明什么是 B+ 树。

[Assistant] 09:47 <<< TARGET
B+ 树是一种多路平衡搜索树…
```

Assistant tool calls are summarized inline as `-> name(arg=value, …)`, so the
commands that were actually executed survive into the drill-down. Thinking
blocks are dropped.

Because pi sessions are trees, the parser resolves a single root-to-leaf path
rather than reading the file in order -- branches left behind by `/fork` or
`/clone` never appear alongside the live conversation.

---

## The memory-recall skill

`memory-recall` tells the model when to reach for these tools and in what order.
It triggers on questions that lean on history -- "what did I decide about X",
"why did we do Y", "have I seen this before" -- and on the
`[memsearch] Memory available.` hint injected into the system prompt.

Unlike the Claude Code plugin, recall runs in the main conversation rather than
a forked subagent: pi skills have no `context: fork` equivalent. The practical
difference is that search results occupy the main context window, which is why
the skill is explicit about stopping early and discarding weak matches.

The skill also documents a fallback for vague questions: read the raw markdown
directly (`ls -t .memsearch/memory/`, `grep -h "^## " …`) to find a concrete
topic, then return to `memory_search` with a specific query.

---

## Other skills

| Skill | Use it for |
|-------|------------|
| `memory-config` | Diagnosing setup, provider routing, index health, `plugins.pi.*` keys |
| `memory-to-skill` | Distilling recurring workflows out of memory into reusable skills |

`memory-to-skill` uses `memory_transcript` when mining history, precisely because
journal bullets are lossy: the exact commands live in the original conversation,
and a distilled skill that guesses at them is worse than one that omits the step.
