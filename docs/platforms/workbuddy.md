# WorkBuddy

MemSearch saves completed WorkBuddy conversations as short Markdown notes in `.memsearch/memory/`. WorkBuddy can search those notes in a new session and follow a note back to the original conversation and tool output. Agents working in the same project share the notes and their index.

## Install the CLI

On the machine running WorkBuddy, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and make Bash and Python 3.10 or later available to the desktop app. On Windows, use Git Bash.

```bash
uv tool install --upgrade "memsearch[onnx]"
memsearch config get plugins.workbuddy.summarize.provider
```

The second command prints the selected provider, or a blank line on a fresh install. If your shell cannot find `memsearch`, run `uv tool update-shell` and open a new terminal. If it reports an unknown key, your CLI predates WorkBuddy support. To use a source checkout, run `uv tool install --force ".[onnx]"` from the repository root.

## Configure memory

**First-time MemSearch users:** select local ONNX embeddings before configuring summaries. This keeps indexing and search on your machine. **If you already use MemSearch, keep your current embedding configuration and skip this command.**

```bash
memsearch config set embedding.provider onnx
```

WorkBuddy uses a named API provider to summarize completed turns. If you already have a provider configured in MemSearch, select it with `memsearch config set plugins.workbuddy.summarize.provider <provider-name>`.

For a new OpenAI provider, export your API key as `OPENAI_API_KEY` in your shell and run the commands below. Choose a model your key can access. These settings go in your user configuration and apply independently of the model selected in WorkBuddy chat.

```bash
memsearch config set llm.providers.openai.type openai
memsearch config set llm.providers.openai.model gpt-5-mini
memsearch config set llm.providers.openai.api_key env:OPENAI_API_KEY
memsearch config set plugins.workbuddy.summarize.provider openai
```

## Enable the desktop plugin

In WorkBuddy, open **Skills → Kits** (技能 → 套件), click **＋** to add a marketplace, and enter `zilliztech/memsearch`. Install **memsearch** from **memsearch-workbuddy**, then fully quit and reopen the app with the API key available to it. On macOS, if you exported the key in Terminal, run `open -a WorkBuddy` from that same terminal after quitting the app.

For a source checkout, enter the absolute path to the repository root as the marketplace source.

## Check capture and recall

In a project conversation, give WorkBuddy a distinctive decision to remember. After its reply, look in the project's `.memsearch/memory/YYYY-MM-DD.md` for the summary. In a fresh conversation in the same project, ask it to recall the decision. For the exact wording or tool output, use `memsearch transcript "<path from the anchor>" --turn "<turn ID>"` on the machine where WorkBuddy recorded the conversation.

If the journal stays empty, check that WorkBuddy can access your selected API provider and that its Stop hook received a readable `transcript_path`.
