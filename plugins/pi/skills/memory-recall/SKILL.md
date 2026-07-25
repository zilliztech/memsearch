---
name: memory-recall
description: "Search and recall relevant memories from past sessions via memsearch. Use when the user's question could benefit from historical context, past decisions, debugging notes, previous conversations, or project knowledge -- especially questions like 'what did I decide about X', 'why did we do Y', or 'have I seen this before'. Also use when you see a `[memsearch] Memory available` hint in the system prompt. Typical flow: search for 3-5 chunks, then expand the most relevant ones. Skip when the question is purely about current code state (use read/grep), ephemeral (today's task only), or the user has explicitly asked to ignore memory."
allowed-tools: memory_search memory_get read bash
---

Retrieve context from past sessions and fold it into your answer.

Memories are shared across agents: the Claude Code, Codex, OpenCode, and OpenClaw
plugins write to the same store, so a conversation from any of them is
searchable here.

## Steps

1. **Search** — call `memory_search` with a query capturing the core intent of
   the user's question. Start with `top_k: 5`.

2. **Evaluate** — skip results that are clearly irrelevant or too generic.
   Scores are normalized to `[0, 1]`; treat low-scoring hits with suspicion.

3. **Expand** — call `memory_get` with the `chunk_hash` of each promising
   result to read the full markdown section with surrounding context.
   Search results are truncated, so expand before relying on a hit.

4. **Answer** — fold the relevant findings into your response. Cite the source
   file and date so the user can trace the claim. Only include what is
   genuinely useful for the question at hand.

## When unsure what to search

If the question is vague and you cannot form a concrete query, explore the raw
markdown first — it is the source of truth, and the vector index is derived
from it:

- `ls -t .memsearch/memory/ | head -10` — recent daily journals
- `grep -h "^## " .memsearch/memory/*.md | sort -u | tail -40` — session
  headings across all days
- `read .memsearch/memory/<YYYY-MM-DD>.md` — read a specific day

Once a concrete topic surfaces, go back to `memory_search` with a specific query.

## Notes

- Expanded chunks may contain an anchor comment
  (`<!-- session:… turn:… transcript:… -->`) pointing at the original
  conversation. Reading that transcript file directly is possible but usually
  unnecessary — the expanded section is normally enough.
- If nothing relevant turns up, say so plainly rather than padding the answer
  with weak matches.
