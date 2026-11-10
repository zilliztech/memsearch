# How It Works

The plugin combines host execution events with a read-only SQLite projection reader. Events trigger immediate work; the database determines what can safely be captured. One finite helper handles a serialized batch, and a project file lock coordinates concurrent host instances.

## Completion and ownership

The reader uses `session_v2` and `session_message`, ordered by the per-session `seq` column. It requires completed assistant messages, settled tools, and a terminal boundary. A streamed response alone does not qualify. Persisted failed/interrupted runs advance without a summary; host shutdown without an idle boundary remains pending for resumption.

A following user message alone does not qualify a live turn; retrying, unfinished, or failed final responses cannot become successful summaries.

Capture, requesting-session checks and L3 use the canonical physical checkout root (or exact non-Git directory) plus workspace. Host project IDs may change and are diagnostic metadata, not ownership or durable cursor keys. Git subdirectories and symlink aliases resolve to their checkout; nested repositories, separate worktrees and unrelated same-name directories stay separate. Session metadata is filtered before selecting message content, and location-switch boundaries exclude prior-location payloads from the query. Subagents and copied fork history are excluded from capture. Synthetic, compaction, reasoning and raw tool content are omitted.

## Durable capture

The helper stores a pending turn before inference. Once summarized, it durably stores the intended append and its file offset/hash, appends and fsyncs the Markdown, commits the sequence cursor, and indexes. It can complete its own partial append or recognize a finished append after a checkpoint failure. Conflicting journal edits stop automatic repair. A failed index remains dirty for retry without appending the summary again.

Capture state lives in `.memsearch/opencode-turns.db`. Markdown is the source of truth, with `<!-- session:... turn:... db:... -->` anchors linking summaries to original conversations. On first activation, existing settled history is baselined atomically; incomplete turns remain eligible. Setup establishes the baseline without inference, then registers tools, Skills and hooks before subscribing to execution events. Subsequent recovery scans replay missed work, including events that arrived during setup.

Completion events wake capture immediately. A 15-second scan covers lost or early events. Recovery also runs before prompts, context injection, search and expansion. Host shutdown has a three-second limit: the plugin gives its helper a short grace period, then cancels it. Pending inference and indexing resume on the next activation before recall. A forced exit can leave work pending.

Search and expansion use a query mode of the same finite helper. It takes the capture/index project lock and revalidates the requesting session after waiting, then runs the CLI query. All plugin-owned index/search/expand commands acquire `~/.memsearch/.opencode-cli.lock` after the project lock, coordinating different checkouts that share HOME and the default Milvus Lite database. The HOME lock is released when the CLI operation completes or is cancelled; it does not cover summaries or optional maintenance. CLI access from other programs is outside this coordination.

## Inference and maintenance

`plugins.opencode.summarize.provider` selects native or a named shared API provider. Native inference calls `ctx.generate.text` with only the bounded summary prompt. It creates no session, invokes no tools and does not include current session history. It never uses `ctx.session.generate`.

Native model precedence is task override → resolved title-agent model → host default. The default applies when title-agent lookup succeeds without a model; lookup failure produces an unavailable note without invoking a different model. Named providers use `memsearch summarize --plugin opencode --agent-name OpenCode`, including provider endpoint, environment-key and model overrides.

Custom `prompts.summarize` overrides the packaged shared prompt. Genuine failures write the established unavailable note; cancellation leaves pending work. Raw dialogue is never a fallback. Disabling summarization prevents calls to either route.

Enabled PROJECT.md/USER.md maintenance and Skill distillation reuse shared Python prompts, provider resolution, due-state and digest logic. A separate finite background helper runs maintenance after capture, without holding the capture lock or delaying prompt/context/search recovery. Shutdown cancels it. Native maintenance uses its task override or host default, via stateless inference. It has no transcript tools; candidate Skills must not invent exact commands requiring L3 verification. Candidates are installed only after an explicit user request.

## Context and recall

The context hook preserves host `SystemPart` metadata while idempotently adding recent daily journal excerpts and recall/candidate hints. Tools and Skills use the requesting session's checkout, and collection defaults never override explicit collection config. See [memory tools](memory-tools.md) for the recall workflow.
