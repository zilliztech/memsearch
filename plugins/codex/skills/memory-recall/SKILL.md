---
name: memory-recall
description: "Search and recall relevant memories from past sessions. Use when the user's question could benefit from historical context, past decisions, debugging notes, previous conversations, or project knowledge. Also use when you see '[memsearch] Memory available' hints."
---

You are performing memory retrieval for memsearch. Search past memories and return the most relevant context to the current conversation.

## Project Collection

Determine the collection name by running:
```
bash -c 'root=$(git rev-parse --show-toplevel 2>/dev/null || true); if [ -n "$root" ]; then bash __INSTALL_DIR__/scripts/derive-collection.sh "$root"; else bash __INSTALL_DIR__/scripts/derive-collection.sh; fi'
```

## Steps

1. **Search**: Run `memsearch search "<query>" --top-k 5 --json-output --collection <collection name from above>` to find relevant chunks.
   - If `memsearch` is not found, try `uvx memsearch` instead.
   - Choose a search query that captures the core intent of the user's question.

2. **Evaluate**: Look at the search results. Skip chunks that are clearly irrelevant or too generic.

3. **Expand**: For each relevant result, get the full context using one of these methods:
   - **Primary**: Run `memsearch expand <chunk_hash> --collection <collection name from above>` to get the full markdown section.
   - **Fallback** (if expand fails with a lock/permission error due to sandbox): Read the source file directly. The search results include `source` (file path) and `start_line`/`end_line` — use `cat <source_file>` or read the relevant line range to get the full context. This avoids the Milvus lock file issue.

4. **Deep drill (optional)**: If an expanded chunk contains transcript anchors (HTML comments with session/rollout info), and the original conversation seems critical:
   - Run `bash __INSTALL_DIR__/scripts/parse-rollout.sh <rollout_path>` to retrieve the original conversation turns.
   - If the anchor format is unfamiliar (e.g. `transcript:` + `turn:`, `db:` instead of `rollout:`), try reading the referenced file directly to explore its structure and locate the relevant conversation by the session or turn identifiers in the anchor.

5. **Return results**: Output a curated summary of the most relevant memories. Be concise — only include information that is genuinely useful for the user's current question.

## Output Format

Organize by relevance. For each memory include:
- The key information (decisions, patterns, solutions, context)
- Source reference (file name, date) for traceability

If nothing relevant is found, simply say "No relevant memories found."
