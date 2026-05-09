# Installation

## Prerequisites

- OpenClaw >= 2026.3.22
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

## Install from ClawHub (recommended)

The plugin is published on [ClawHub](https://clawhub.ai/plugins/memsearch).

```bash
# 1. Install the plugin
openclaw plugins install --force clawhub:memsearch

# 2. Allow memsearch to read conversation turns and inject recall context
openclaw config set plugins.entries.memsearch.hooks.allowConversationAccess true
openclaw config set plugins.entries.memsearch.hooks.allowPromptInjection true

# 3. Restart the gateway
openclaw gateway restart
```

## Install from Source (development)

```bash
# 1. Clone the memsearch repo (if not already)
git clone https://github.com/zilliztech/memsearch.git

# 2. Install the OpenClaw plugin
openclaw plugins install --force ./memsearch/plugins/openclaw

# 3. Allow memsearch to read conversation turns and inject recall context
openclaw config set plugins.entries.memsearch.hooks.allowConversationAccess true
openclaw config set plugins.entries.memsearch.hooks.allowPromptInjection true

# 4. Restart the gateway
openclaw gateway restart
```

## Configuration

```bash
openclaw plugins config memsearch
```

| Setting | Default | Description |
|---------|---------|-------------|
| `provider` | `onnx` | Embedding provider |
| `autoCapture` | `true` | Auto-capture conversations |
| `autoRecall` | `true` | Auto-inject recent memories on agent start |

For Milvus backend configuration, run `memsearch config set milvus.uri <uri>`.

## Updating

For ClawHub installs, install the plugin again and restart the gateway:

```bash
openclaw plugins install --force clawhub:memsearch
openclaw config set plugins.entries.memsearch.hooks.allowConversationAccess true
openclaw config set plugins.entries.memsearch.hooks.allowPromptInjection true
openclaw gateway restart
```

For source installs, pull the latest repo, reinstall from the local plugin directory, and restart:

```bash
cd memsearch
git pull
openclaw plugins install --force ./plugins/openclaw
openclaw config set plugins.entries.memsearch.hooks.allowConversationAccess true
openclaw config set plugins.entries.memsearch.hooks.allowPromptInjection true
openclaw gateway restart
```

## Uninstall

```bash
openclaw plugins uninstall memsearch
openclaw gateway restart
```

Uninstalling the plugin does not delete memory files in `.memsearch/memory/`.
