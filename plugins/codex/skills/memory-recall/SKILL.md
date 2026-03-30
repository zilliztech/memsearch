---
name: memory-recall
description: "Search and recall relevant memories from past sessions. Use when the user's question could benefit from historical context, past decisions, debugging notes, previous conversations, or project knowledge. Also use when you see '[memsearch] Memory available' hints."
---

You are performing memory retrieval for memsearch. Search past memories and return the most relevant context to the current conversation.

## Project Collection

Determine the collection name by running:
```
bash __INSTALL_DIR__/scripts/derive-collection.sh
```

## Steps

1. **Search**: Run `memsearch search "<query>" --top-k 5 --json-output --collection <collection name from above>` to find relevant chunks.
   - If `memsearch` is not found, try `uvx memsearch` instead.
   - Choose a search query that captures the core intent of the user's question.

2. **Evaluate**: Look at the search results. Skip chunks that are clearly irrelevant or too generic.

3. **Expand**: For each relevant result, get the full context using one of these methods:
   - **Primary**: Run `memsearch expand <chunk_hash> --collection <collection name from above>` to get the full markdown section.
   - **Fallback** (if expand fails with a lock/permission error due to sandbox): Read the source file directly. The search results include `source` (file path) and `start_line`/`end_line` — use `cat <source_file>` or read the relevant line range to get the full context. This avoids the Milvus lock file issue.

4. **Deep drill (optional)**: If an expanded chunk contains rollout anchors (rollout path in HTML comment), and the original conversation seems critical, run:
   ```
   bash __INSTALL_DIR__/scripts/parse-rollout.sh <rollout_path>
   ```
   to retrieve the original conversation turns.

5. **Return results**: Output a curated summary of the most relevant memories. Be concise — only include information that is genuinely useful for the user's current question.

## Output Format

Organize by relevance. For each memory include:
- The key information (decisions, patterns, solutions, context)
- Source reference (file name, date) for traceability

If nothing relevant is found, simply say "No relevant memories found."
