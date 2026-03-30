# Memory Recall

When Claude detects that a user's question could benefit from past context, it automatically invokes the `memory-recall` skill. The skill runs in a **forked subagent context** (`context: fork`), meaning it has its own context window and does not pollute the main conversation.

---

## Three-Layer Progressive Disclosure

The memory-recall skill uses a three-layer progressive disclosure model. Each layer provides increasing detail, and the subagent autonomously decides how deep to drill based on the query:

```mermaid
graph TD
    SKILL["memory-recall skill<br/>(context: fork subagent)"]
    SKILL --> L1["L1: Search<br/>(memsearch search)"]
    L1 --> L2["L2: Expand<br/>(memsearch expand)"]
    L2 --> L3["L3: Transcript drill-down<br/>(memsearch transcript)"]
    L3 --> RETURN["Curated summary<br/>to main agent"]

    style SKILL fill:#2a3a5c,stroke:#6ba3d6,color:#a8b2c1
    style L1 fill:#2a3a5c,stroke:#6ba3d6,color:#a8b2c1
    style L2 fill:#2a3a5c,stroke:#e0976b,color:#a8b2c1
    style L3 fill:#2a3a5c,stroke:#d66b6b,color:#a8b2c1
    style RETURN fill:#2a3a5c,stroke:#7bc67e,color:#a8b2c1
```

| Layer | Command | What it returns | When to use |
|-------|---------|----------------|-------------|
| **L1: Search** | `memsearch search "<query>" --top-k 5 --json-output` | Top-K relevant chunk snippets with scores | Always -- the starting point for every recall |
| **L2: Expand** | `memsearch expand <chunk_hash>` | Full markdown section with anchor metadata | When a snippet looks relevant but needs more context |
| **L3: Transcript** | `python3 transcript.py <jsonl> --turn <uuid> --context 3` | Original conversation turns verbatim | When you need the exact exchange -- what was tried, what failed, what was decided |

The subagent autonomously searches, evaluates relevance, expands promising results, and drills into transcripts when needed. Only the curated summary reaches the main conversation.

---

## Real-World Example

Here is what a typical memory recall looks like from the user's perspective. The user asks a question, Claude invokes the skill, and the subagent does multi-step retrieval behind the scenes:

**User prompt:**
```
The /orders endpoint is still slow after yesterday's fix. What did we do?
```

**Behind the scenes (in the forked subagent):**

1. **L1 Search** -- the subagent runs `memsearch search "orders endpoint performance fix" --top-k 5 --json-output` and gets back:
    ```
    Score 0.82: "Fixed N+1 query in order-service using selectinload..."
    Score 0.71: "Added Redis caching middleware with 5min TTL..."
    Score 0.65: "Decided to use Prometheus counters for cache hit/miss..."
    ```

2. **L2 Expand** -- the top result looks directly relevant, so the subagent runs `memsearch expand <chunk_hash>`:
    ```markdown
    ### 14:30
    <!-- session:abc123 turn:def456 transcript:/home/user/.claude/projects/.../abc123.jsonl -->
    - Fixed N+1 query issue in order-service using selectinload
    - Changed get_orders() to eager-load order_items relationship
    - Added index on order.user_id for the new query pattern
    - Before: 47 queries per page load; after: 2 queries
    ```

3. **L3 Transcript** (optional) -- the subagent decides it has enough context and skips L3.

**What Claude returns to the user:**
```
Yesterday we fixed the /orders endpoint performance:

- Replaced the N+1 query in get_orders() with SQLAlchemy selectinload
  to eager-load order_items (went from 47 queries to 2 per page load)
- Added a database index on order.user_id
- Also added Redis caching middleware with 5min TTL

If it's still slow, the issue may be elsewhere -- perhaps the Redis
cache isn't being hit for this endpoint. Let me check the cache
middleware configuration...
```

The user sees a concise, contextual answer. The intermediate search results, chunk hashes, and expansion steps all happened in the forked subagent's context and never entered the main conversation.

---

## Manual Invocation

Users can also manually invoke the skill:

```
/memory-recall <query>
```

This is useful when:

- You want to explicitly search past sessions for a specific topic
- Claude doesn't automatically trigger the recall (some questions don't obviously need historical context)
- You want to verify what Claude "remembers" about a past session

---

## Tips for Better Recall

**Use specific queries.** "Redis caching" will return better results than "the thing we did last week". The search uses both semantic similarity (dense vectors) and keyword matching (BM25), so including specific terms helps.

**Check cold-start context.** The SessionStart hook injects the last 30 lines from recent daily logs. For very recent work (today or yesterday), Claude may already have the context without needing to invoke the skill.

**Don't over-manage.** The system is designed to be autonomous. You don't need to tell Claude to "check memory" -- if the question benefits from historical context, the `UserPromptSubmit` hint and Claude's own judgment will trigger the skill.

**Edit memory files directly.** If a summary is inaccurate or contains sensitive information, open `.memsearch/memory/YYYY-MM-DD.md` in your editor and fix it. The watcher will re-index automatically. Memory files are plain markdown -- you're in full control.

**Rebuild the index if search quality degrades.** If you change embedding providers or suspect index corruption:
```bash
memsearch index .memsearch/memory/ --force
```

---

## Comparison with claude-mem's Recall

Both memsearch and [claude-mem](https://github.com/thedotmack/claude-mem) provide memory recall for Claude Code, but the retrieval architecture differs significantly:

| Aspect | memsearch | claude-mem |
|--------|-----------|------------|
| **Recall trigger** | Skill auto-invoked by Claude based on context | `mem-search` skill + 5 MCP tools available in main context |
| **Execution context** | Forked subagent (`context: fork`) -- isolated context window | Main conversation context -- tool calls visible |
| **Intermediate results** | Never enter main context | Each MCP tool call/result consumes main context tokens |
| **Search approach** | Hybrid: dense + BM25 + RRF fusion | Dense only (ChromaDB); keyword search via separate SQLite FTS5 |
| **Progressive depth** | Autonomous: subagent decides search → expand → transcript | Manual: user/Claude explicitly calls MCP tools |
| **Context cost** | Zero -- no MCP tool definitions loaded | 5 MCP tool schemas permanently in context |

The forked subagent design means memsearch's recall is **invisible to the main conversation**. The user sees only the curated summary, not the intermediate search steps. This keeps the main context window clean and focused on the actual task.

---

## Comparison with Claude's Native Memory Recall

Claude Code's built-in memory (`CLAUDE.md` and auto-memory files) has no recall mechanism at all -- the entire file is loaded at session start regardless of relevance. This creates two problems:

1. **No selective recall.** Claude cannot search for a specific decision from three weeks ago. Either it's in the loaded file or it's not available.
2. **Context waste.** As `CLAUDE.md` grows, irrelevant instructions consume context tokens on every session, reducing the window available for actual work.

memsearch's skill-based recall solves both: memories are only loaded when relevant (via semantic search), and the three-layer model lets the subagent fetch exactly the right amount of detail -- from a one-line snippet to the full original conversation.
