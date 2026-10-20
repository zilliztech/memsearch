# Memory Tools

The V2 source registers exactly three tools. They validate the requesting session's project, checkout and persisted workspace, and use its configured collection. `--default-collection` supplies a derived fallback without overriding explicit config.

| Tool | Arguments | Result |
|---|---|---|
| `memory_search` | `query` (1–4000 characters), optional `top_k` (1–20; default 5) | JSON chunks with `chunk_hash`, including short results. |
| `memory_get` | `chunk_hash` | Full Markdown section and transcript anchors. |
| `memory_transcript` | `session_id`, optional `turn_id`, `db_path`, `limit` (1–50; default 20), `context` (0–10; default 3) | Original V2 user/assistant dialogue around the selected turn or recent turns. |

Search first, evaluate relevance, then expand promising chunks. For a claim requiring original evidence, copy `session:`, `turn:` and `db:` from the expanded anchor into the transcript tool. Turn IDs match exactly or by an unambiguous prefix. The optional `db_path` honors anchors pointing to another database, while session ownership remains mandatory.

Search and expansion attempt pending capture/index recovery first. A recovery diagnostic does not erase existing memories; older L1/L2 results remain useful. Transcript lookup reads the selected database directly and read-only, without requiring a sidecar or model inference. Its bounded rendering excludes tool output and reasoning.

If a referenced database, session or turn is absent, state that the original dialogue could not be verified. If the schema is unsupported or an upgrade left the conversation unavailable, direct the user to [OpenCode's migration guidance](https://opencode.ai/v2/docs/migrate-v1). Keep Markdown and anchors unchanged, and do not scan unrelated transcripts. MemSearch does not perform the host migration.

The packaged `memory-recall` Skill guides this workflow. `memory-config` diagnoses shared settings; `memory-to-skill` reviews candidate workflows and requires the user's request before installation. All three register through the V2 Skill API with actual file paths for references.
