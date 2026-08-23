# Install the DeepSeek Harness Plugin

## Prerequisites

- Python 3.10+
- Node.js 22.19 or newer, as required by DSH
- A DSH profile such as `web`, `tui`, or `headless`
- The `dsh` command available on `PATH`

## 1. Install MemSearch

The default ONNX embedding provider runs locally and does not require an API key:

```bash
uv tool install "memsearch[onnx]"
```

The embedding model downloads from Hugging Face the first time it is used and is cached afterward.

## 2. Add the Plugin to a DSH Profile

Install the published npm package into the profile you use:

```bash
dsh plugin --profile web add @zilliz/memsearch-dsh
```

Replace `web` with another profile name when appropriate. The command adds the package to that profile and inserts the MemSearch plugin into its bundle layers.

Restart the profile, or begin a new DSH session, so the plugin mounts.

### Install from Source

Use a local checkout when developing the plugin:

```bash
git clone https://github.com/zilliztech/memsearch.git
dsh plugin --profile web add /absolute/path/to/memsearch/plugins/dsh
```

The plugin is plain ESM with no build step. Restart the profile after changing the plugin source.

## 3. Verify the Installation

Complete a normal DSH turn, then check the project memory directory:

```bash
ls .memsearch/memory/
cat .memsearch/memory/$(date +%Y-%m-%d).md
```

You can also ask DSH to use the registered skill:

```text
Use memory-recall to search for our earlier database migration decision.
```

In a web profile, look for the compact **MemSearch** capsule above the composer. Expanding it shows skill candidates and the read-only `.memsearch` browser.

## Plugin Settings

The plugin works without configuration. Its DSH profile settings control lifecycle behavior:

| Setting | Default | Purpose |
|---------|---------|---------|
| `captureEnabled` | `true` | Capture completed turns into the daily memory journal |
| `injectEnabled` | `true` | Search and inject relevant memory before the first model step |
| `summarizeEnabled` | `true` | Summarize turns before writing them |
| `summarizeMode` | `auto` | Use a configured API provider when present; otherwise use a one-shot DSH headless agent |

To override these settings, patch the `memsearch` row in the profile's `cordis.patch.yml`:

```yaml
- id: memsearch
  config:
    captureEnabled: true
    injectEnabled: true
    summarizeMode: auto
```

Embedding, Milvus, and provider settings continue to live in the shared MemSearch configuration. For example, to route DSH capture summarization through a configured provider:

```bash
memsearch config set llm.providers.openai.type openai
memsearch config set llm.providers.openai.model gpt-5-mini
memsearch config set llm.providers.openai.api_key env:OPENAI_API_KEY
memsearch config set plugins.dsh.summarize.provider openai
```

Leave `plugins.dsh.summarize.provider` unset to use the DSH headless-agent default. Setting a provider selects the direct `custom-llm` route. See [How It Works](how-it-works.md#summarization) for the backend behavior.

## Optional Maintenance

These background tasks are disabled by default:

```bash
memsearch config set plugins.dsh.project_review.enabled true
memsearch config set plugins.dsh.user_profile.enabled true
memsearch config set plugins.dsh.memory_to_skill.enabled true
```

They maintain `.memsearch/PROJECT.md`, `.memsearch/USER.md`, and `.memsearch/skill-candidates/`. Skill candidates remain inert until you choose to install one.

## Update

Update the package in the selected profile, then restart that profile:

```bash
dsh plugin --profile web update @zilliz/memsearch-dsh
```

## Uninstall

```bash
dsh plugin --profile web remove @zilliz/memsearch-dsh
```

Removing the plugin does not delete `.memsearch` markdown files or the Milvus index.

## Troubleshooting

- **No memory file appears:** confirm the plugin mounted in the DSH session log and that `captureEnabled` is still `true`.
- **The recall skill is missing:** restart the profile after installation and confirm `@zilliz/memsearch-dsh` is present in that profile.
- **Summarization reports an unavailable note:** verify `dsh` is on `PATH`, or check the configured `[plugins.dsh.summarize]` provider.
- **The web dock is absent:** the dock requires a web profile; capture, injection, and recall still work in TUI and headless profiles.
- **First search cannot download the model:** pre-cache the ONNX model from an environment with access to Hugging Face, or configure another [embedding provider](../../home/configuration.md).
