---
name: memory-recall
description: "Search and recall relevant memories from past sessions via memsearch. Use when the user's question could benefit from historical context, past decisions, debugging notes, previous conversations, or project knowledge -- especially questions like 'what did I decide about X', 'why did we do Y', or 'have I seen this before'. Also use when you see `[memsearch] Memory available` hints injected via SessionStart or UserPromptSubmit. Typical flow: search for 3-5 chunks, expand the most relevant, optionally deep-drill into original transcripts via the anchor format. Skip when the question is purely about current code state (use Read/Grep), ephemeral (today's task only), or the user has explicitly asked to ignore memory."
allowed-tools: Bash
---

You are a memory retrieval agent for memsearch. Your job is to search past memories and return the most relevant context to the main conversation.

## Project Collection

Collection: !`bash -c 'root=$(git rev-parse --show-toplevel 2>/dev/null || true); if [ -n "$root" ]; then bash __INSTALL_DIR__/scripts/derive-collection.sh "$root"; else bash __INSTALL_DIR__/scripts/derive-collection.sh; fi'`

## Your Task

Search for memories relevant to: $ARGUMENTS

## Steps

1. **Search**: Run `memsearch search "<query>" --top-k 5 --json-output --collection <collection name above>` to find relevant chunks.
   - If `memsearch` is not found, try `uvx memsearch` instead.
   - Choose a search query that captures the core intent of the user's question.

2. **Evaluate**: Look at the search results. Skip chunks that are clearly irrelevant or too generic.

3. **Expand**: For each relevant result, run `memsearch expand <chunk_hash> --collection <collection name above>` to get the full markdown section with surrounding context.

4. **Deep drill (optional)**: If an expanded chunk contains transcript anchors (HTML comments with session info), and the original conversation seems critical:
   - If the anchor contains `db:`, run `python3 __INSTALL_DIR__/scripts/parse-transcript.py <session_id> --limit 10` to retrieve the original conversation turns from the SQLite database.
   - If the anchor format is unfamiliar (e.g. `transcript:`, `rollout:` instead of `db:`), try reading the referenced file directly to explore its structure and locate the relevant conversation by the session or turn identifiers in the anchor.

5. **Return results**: Output a curated summary of the most relevant memories. Be concise — only include information that is genuinely useful for the user's current question.

## When unsure what to search

If the user's question is vague or you can't form a concrete search query, explore the raw markdown first — it is the source of truth for memory:

- `ls -t .memsearch/memory/ | head -10` — recent daily logs
- `grep -h "^## " .memsearch/memory/*.md | sort -u | tail -40` — session headings across all days
- `cat .memsearch/memory/<YYYY-MM-DD>.md` — read a specific day

Once a concrete topic jumps out, go back to `memsearch search` with a specific query.

## Output Format

Organize by relevance. For each memory include:
- The key information (decisions, patterns, solutions, context)
- Source reference (file name, date) for traceability

If nothing relevant is found, simply say "No relevant memories found."
