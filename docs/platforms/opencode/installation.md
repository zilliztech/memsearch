# Installation

## Prerequisites

- OpenCode with plugin support
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

## Automated Install

```bash
bash memsearch/plugins/opencode/install.sh
```

The installer:

1. Symlinks the plugin to `~/.config/opencode/plugins/memsearch.ts`
2. Symlinks the memory-recall skill to `~/.agents/skills/memory-recall`
3. Installs npm dependencies
4. Shows next steps

## Manual Installation

1. Add to your `opencode.json`:

    ```json
    {
      "plugin": ["memsearch-opencode"]
    }
    ```

2. Install the npm package:

    ```bash
    npm install --save-dev @opencode-ai/plugin
    ```

## Configuration

The plugin defaults to ONNX embedding (no API key). Configuration uses the standard memsearch config system:

```bash
memsearch config set embedding.provider onnx
memsearch config set milvus.uri http://localhost:19530  # optional: remote Milvus
```
