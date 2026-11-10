---
name: memory-recall
description: "Search and recall relevant memories from past sessions via MemSearch. Use for past decisions, debugging notes, previous conversations, and project knowledge, especially when the context includes a MemSearch memory hint. Skip purely current-code questions or when the user asks to ignore memory."
---

Search memories relevant to the user's current question. The plugin's tools resolve the requesting session's checkout and configured collection, and recover pending capture before recall.

## Steps

1. Use `memory_search` with a concrete query and `top_k: 5`. It returns text containing a JSON array of objects with `chunk_hash`, `content` and `source`. When calling through `execute`, return the search result and inspect its text before selecting hashes. Evaluate relevance before expanding results.
2. Use `memory_get` with the most promising `chunk_hash` values to read full Markdown sections.
3. For claims requiring original dialogue, use `memory_transcript` with `session_id`, `turn_id` and `db_path` from the expanded `session:` / `turn:` / `db:` anchor. Set `context: 3`; for an anchor without a turn, use `limit: 10`.
   - If OpenCode transcript lookup fails after an upgrade, distinguish an incompatible host/plugin pair, an unavailable database or session/turn, and an incomplete V1-to-V2 database migration. See [OpenCode diagnostics](../memory-config/references/opencode.md), also used by `memory-config`. Check the referenced conversation only; a lookup failure does not justify scanning unrelated transcripts.
   - Keep existing markdown and `session:` / `turn:` / `db:` anchors unchanged. Return useful search/expand results with the L3 limitation stated. If host migration is needed, direct the user to OpenCode's migration guidance; do not migrate the database or rewrite anchors during recall. Do not describe a summary as verified original dialogue.

4. Return a concise account of relevant facts with dates and source files. Distinguish journal summaries from verified dialogue. If nothing relevant is found, say so.

If the query is unclear, inspect recent daily Markdown files under `.memsearch/memory/` to identify a topic, then search. Avoid unrelated memory and transcript scans. A capture-pending diagnostic means new memories may still be recovering; existing Markdown/search results remain useful.

These tools require OpenCode V2. V1 users pin the published `@zilliz/memsearch-opencode@0.3.17`. Plugin 0.4.0 supports OpenCode >=2.0.32 <3. OpenCode's own database migration remains user-owned.
