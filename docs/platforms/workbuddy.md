# WorkBuddy

MemSearch saves completed WorkBuddy conversations as short Markdown notes in `.memsearch/memory/`. WorkBuddy can search those notes in a new session and follow a note back to the original conversation and tool output. Agents working in the same project share the notes and their index.

## Install

1. Install the MemSearch CLI on the machine running WorkBuddy. The plugin needs Bash and Python 3.10 or later. On Windows, make Git Bash available to the desktop app.

    ```bash
    uv tool install --upgrade "memsearch[onnx]"
    memsearch config get plugins.workbuddy.summarize.provider
    ```

    An empty result means the CLI recognizes WorkBuddy and you can configure a provider. If the command reports an unknown key, install the CLI from the same source checkout as the plugin by running `uv tool install --force ".[onnx]"` in the repository root.

2. In WorkBuddy, open **Skills → Kits** (技能 → 套件), click **＋** to add a marketplace, and enter `zilliztech/memsearch`. Install **memsearch** from **memsearch-workbuddy** and restart WorkBuddy. To test a source checkout, use its absolute directory path as the marketplace source.

## Configure summaries

WorkBuddy uses a named API provider for summaries. If you already use one with MemSearch, run `memsearch config set plugins.workbuddy.summarize.provider <provider-name>`. For example, to configure an OpenAI provider:

```bash
memsearch config set llm.providers.openai.type openai
memsearch config set llm.providers.openai.model gpt-5-mini
memsearch config set llm.providers.openai.api_key env:OPENAI_API_KEY
memsearch config set plugins.workbuddy.summarize.provider openai
```

Choose a model your API key can use, and make the referenced environment variable available to the WorkBuddy desktop process. These commands write to your user configuration. The summary model is independent of the chat model selected in WorkBuddy. New installations use local ONNX embeddings by default.

## Check capture and recall

In a project conversation, give WorkBuddy a distinctive decision to remember. After its reply, look in the project's `.memsearch/memory/YYYY-MM-DD.md` for the summary. In a fresh conversation in the same project, ask it to recall the decision. For the exact wording or tool output, use `memsearch transcript "<path from the anchor>" --turn "<turn ID>"` on the machine where WorkBuddy recorded the conversation.

If the journal stays empty, check that WorkBuddy can access your selected API provider and that its Stop hook received a readable `transcript_path`.
