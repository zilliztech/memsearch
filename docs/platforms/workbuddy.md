# WorkBuddy preview

This fork contains a marketplace preview for the WorkBuddy desktop app. It uses the same Markdown journals, project collections and recall skill as the Claude Code plugin. Summaries use a named API provider; WorkBuddy's chat model and subscription are independent.

## Install and configure

1. On the machine running WorkBuddy, clone the preview and install its matching CLI. The hooks require Bash and Python 3. On Windows make Git Bash available to the desktop app.

    ```bash
    git clone --depth 1 --branch codex/workbuddy-preview https://github.com/zc277584121/memsearch.git memsearch-workbuddy-preview
    cd memsearch-workbuddy-preview
    uv tool install --force ".[onnx]"
    memsearch config get plugins.workbuddy.summarize.provider
    ```

    The last command should succeed (an empty value is fine). The tool install updates the `memsearch` command on this machine. If you already have a named summary provider, select it with `memsearch config set plugins.workbuddy.summarize.provider <provider-name>`.

2. For a fresh setup, put the following in your user configuration (`~/.memsearch/config.toml`). If the file already exists, add only the missing settings. Choose a model your API key can access and make the referenced environment variable available to the desktop app. Keep the credential out of the project repository.

    ```toml
    [embedding]
    provider = "onnx"

    [llm.providers.wb]
    type = "openai"
    model = "<your API model>"
    api_key = "env:OPENAI_API_KEY"

    [plugins.workbuddy.summarize]
    provider = "wb"
    ```

3. In WorkBuddy, open **专家·技能·连接器 → 技能 → 套件 → ＋** and add the **absolute path of the cloned repository** as a marketplace. If your build accepts a Git URL with a branch, the equivalent source is `https://github.com/zc277584121/memsearch.git#codex/workbuddy-preview`. Select **memsearch** from **memsearch-workbuddy-preview**, install it, then restart WorkBuddy. A plain repository URL selects the default branch, which does not contain the preview.

## Check capture and recall

Open a **separate test project** in WorkBuddy. Give it a distinctive decision, for example: “Remember: the staging cache expires after 37 minutes; we call that rule Blue Lantern.” After the reply, look in that project's `.memsearch/memory/YYYY-MM-DD.md` for a summary and an anchor with the session, user message ID and transcript path. In a fresh conversation in the **same project**, ask it to use memory to recall the staging cache rule without repeating the answer. To verify the original wording, run `memsearch transcript "<path from the anchor>" --turn "<turn ID>"`.

An unconfigured provider or a Stop hook without a readable transcript will not write a summary. Check the hook diagnostics if the journal stays empty. WorkBuddy keeps the raw JSONL on the machine where the conversation took place.
