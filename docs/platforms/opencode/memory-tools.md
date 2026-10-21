# Memory Tools

The plugin provides three tools for finding memories and reading the conversations behind them. They use the requesting session's project, checkout, workspace, and configured collection.

| Tool | Arguments | Result |
|---|---|---|
| `memory_search` | `query` (1–4000 characters), optional `top_k` (1–20; default 5) | JSON chunks with `chunk_hash`, including short results. |
| `memory_get` | `chunk_hash` | Full Markdown section and transcript anchors. |
| `memory_transcript` | `session_id`, optional `turn_id`, `db_path`, `limit` (1–50; default 20), `context` (0–10; default 3) | Original user/assistant dialogue around the selected turn or recent turns. |

Search first, evaluate relevance, then expand promising chunks. For a claim requiring original evidence, copy `session:`, `turn:` and `db:` from the expanded anchor into the transcript tool. Turn IDs match exactly or by an unambiguous prefix.

Omitting `db_path` uses the current host database already resolved by the plugin. Supplying it selects that explicit database, including when an anchor points to another database; copy the anchor's path exactly. A lookup failure in the selected database is reported without retrying against the default database. Session ownership remains mandatory in either case.

Search and expansion attempt pending capture/index recovery first. A recovery diagnostic does not erase existing memories; older L1/L2 results remain useful. Transcript lookup reads the selected database directly and read-only, without requiring a sidecar or model inference. Its bounded rendering excludes tool output and reasoning.

If a referenced database, session or turn is absent, report that the original dialogue could not be verified. Search and expansion results can still provide useful context; distinguish those summaries from verified original dialogue.

The packaged `memory-recall` Skill guides this workflow. `memory-config` diagnoses shared settings; `memory-to-skill` reviews candidate workflows and requires the user's request before installation. All three register through OpenCode's Skill API with actual file paths for references.

Tools are available independently of these Skills. OpenCode lists the Skills for the model to select or the user to invoke; their full instructions are loaded on invocation.

## Troubleshooting

For loading or transcript errors, check the actual loaded plugin and OpenCode versions, then the anchor's database path and session/turn. Plugin 0.4.0 supports OpenCode `>=2.0.32 <3`; OpenCode 1.x users can pin `@zilliz/memsearch-opencode@0.3.17` in their `plugin` array. If earlier conversations need migration, follow [OpenCode's migration guide](https://opencode.ai/v2/docs/migrate-v1); MemSearch leaves that database and the Markdown anchors unchanged.
