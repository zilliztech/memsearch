# Antigravity

MemSearch gives Antigravity persistent project memory. Completed conversation
turns become short Markdown notes, and a new conversation can search those notes,
expand the surrounding context, and trace a decision back to the original
conversation and tool output.

The plugin bundles native lifecycle hooks and the `memory-recall`,
`memory-config`, and `memory-to-skill` skills. Summaries use **Gemini 4 Hydrogen
Low** through your existing Antigravity login. Local ONNX embeddings are the
default for new users; existing MemSearch configuration takes precedence.

[Install the plugin](installation.md) · [How it works](how-it-works.md)

## Daily use

Chat in your project as usual. After each completed turn, MemSearch writes a
summary under `.memsearch/memory/` and updates the Milvus index in the background.

In a new conversation, ask about earlier work:

```text
What did we decide about retrying failed imports, and why?
```

You can also invoke the recall skill explicitly:

```text
/memory-recall find the import retry decision and its original conversation
```

Recall starts with a few relevant snippets, expands useful Markdown sections,
and reads the original transcript when exact wording or tool output matters.
The same project's notes are shared with the other MemSearch plugins.

## Background maintenance

Optional tasks maintain `.memsearch/PROJECT.md`, `.memsearch/USER.md`, and
reusable skill candidates. They use the same configuration, scheduling, and
candidate review workflow as the other plugins. Enable them through
`memory-config` or the [configuration commands](installation.md#background-maintenance).

Candidates are drafts. Use `memory-to-skill` to review and install them into
the project's `.agents/skills/` directory.
