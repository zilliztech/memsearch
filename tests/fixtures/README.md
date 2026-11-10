# Codex rollout fixtures

These fixtures contain only synthetic, non-sensitive text and the fields needed
to test the capture parser. They deliberately omit timestamps, paths, tokens,
credentials, model metadata, private instructions, and unrelated transcript
content.

- `codex_rollout_old.jsonl` is a synthetic compatibility model of the legacy
  dual-write shape. Shared synthetic IDs provide affirmative identity for the
  two representations of each logical message.
- `codex_rollout_0_153.jsonl` is derived from the static persistence policy in
  the official OpenAI Codex `rust-v0.153.4` source tag. That policy permits
  paginated history where natural-language text is carried by `response_item`
  messages while tool, reasoning, and metadata records remain separate. It is
  not a fixture captured from a successful 0.153.4 runtime session.
- `codex_rollout_mixed.jsonl` is a compatibility fixture that combines both
  schemas, two turn boundaries, legal repeated text, and assistant phases.
- `codex_rollout_host_envelopes.jsonl` is a synthetic model of a leading
  developer record, a bare AGENTS header with a composite instructions and
  environment envelope, non-conversational turn records, and a later real user
  message.

A controlled Codex 0.147.0 TUI run produced the response-item-only
conversational shape and the leading sequence of developer context, a
structured environment envelope, and the real user message. The source rollout
was inspected only through structural summaries and the synthetic marker used
for that run; no private transcript was copied into these fixtures. The
separate isolated 0.153.4 TUI stopped at authentication and remains
`NO_CREDIT` for runtime-schema evidence.
