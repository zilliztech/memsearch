# Installation

Use OpenCode with Node.js 22+ and Python 3.11+. Install the MemSearch CLI with local embedding support:

```bash
uv tool install 'memsearch[onnx]'
```

## Install the plugin

Install the package through OpenCode:

```bash
opencode plugin add @zilliz/memsearch-opencode
```

You can also add it to the `plugins` array in `opencode.json`:

```json
{
  "plugins": ["@zilliz/memsearch-opencode"]
}
```

Keep one MemSearch entry alongside your other plugins. Restart OpenCode to load the plugin and its three Skills: `memory-recall`, `memory-config`, and `memory-to-skill`.

## Start using memory

Open a project and have a conversation. Completed turns are summarized into the project's `.memsearch/memory/` directory and indexed automatically. In a fresh session, ask about that conversation to use the memory tools.

Capture starts with new turns after the plugin is activated. Existing MemSearch journals are searchable; earlier OpenCode conversations are not bulk-imported. Each checkout has its own memory collection by default, and an explicitly configured collection takes precedence. Embedding, provider, and model options use the shared [MemSearch configuration](../../home/configuration.md).

## Development source

From a source clone, prepare the plugin dependencies:

```bash
bash plugins/opencode/install.sh
```

The script prints the absolute plugin directory to add to your configuration:

```json
{
  "plugins": ["/absolute/path/to/memsearch/plugins/opencode"]
}
```

Use this directory as the only MemSearch entry, retaining other plugins. Skills register from the package automatically. Restart OpenCode after source changes and verify the loaded path and the three memory tools.

For loading or transcript lookup problems, see [troubleshooting](memory-tools.md#troubleshooting).
