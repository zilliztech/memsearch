# WorkBuddy

WorkBuddy shares MemSearch's shell hooks and Markdown memory with Claude Code. Select an existing named API provider with `memsearch config set plugins.workbuddy.summarize.provider <name>`; the model and API key come from `llm.providers.<name>`. The desktop app must be able to access the configured key and a MemSearch CLI with WorkBuddy support. An empty or `native` provider skips capture. The model selected in the chat UI does not choose the summary model.

If capture is missing, check the workspace, the provider and whether the Stop hook supplied a readable `transcript_path`. Use the transcript referenced by the journal, never another session's newest file. WorkBuddy runs capture and recall only.
