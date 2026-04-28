# Installation

## Prerequisites

- OpenCode with plugin support
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`
- POSIX shell environment for the plugin helper scripts (`bash` + `python3`)

!!! warning "Native Windows is not supported yet"
    The OpenCode plugin currently shells out to `bash` and `python3` helper scripts for collection derivation, transcript parsing, and the background capture daemon. On a plain Windows install without a POSIX shell, the plugin may fail with errors like `derive-collection.sh: No such file or directory`.

    Recommended options:

    - Run OpenCode + memsearch inside [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)
    - Or use Git Bash / another POSIX-compatible shell and expect some path-handling rough edges

    If you need native Windows support, track [issue #387](https://github.com/zilliztech/memsearch/issues/387).

## Verify the plugin is working

After restarting OpenCode, use this quick checklist:

1. Open a project and chat for a few turns.
2. Confirm memory files appear:

```bash
ls .memsearch/memory/
```

3. Inspect today's memory file:

```bash
cat .memsearch/memory/$(date +%Y-%m-%d).md
```

4. Ask a recall question in OpenCode, for example:

```text
We discussed the authentication flow before, what was the approach?
```

If capture is working, you should see daily markdown files appear and the agent should be able to use `memory_search` / `memory_get` / `memory_transcript` when history is relevant.

## Install from npm (recommended)

Add to your `~/.config/opencode/opencode.json`:

```json
{
  "plugin": ["@zilliz/memsearch-opencode"]
}
```

## Install from Source (development)

```bash
bash memsearch/plugins/opencode/install.sh
```

The installer:

1. Symlinks the plugin to `~/.config/opencode/plugins/memsearch.ts`
2. Symlinks the memory-recall skill to `~/.agents/skills/memory-recall`
3. Installs npm dependencies
4. Shows next steps

## Configuration

The plugin defaults to ONNX embedding (no API key). Configuration uses the standard memsearch config system:

```bash
memsearch config set embedding.provider onnx
memsearch config set milvus.uri http://localhost:19530  # optional: remote Milvus
```

## Updating

For npm installs, keep the package name in `~/.config/opencode/opencode.json` and restart OpenCode so it reloads the configured plugin:

```json
{
  "plugin": ["@zilliz/memsearch-opencode"]
}
```

If you pinned a package version in that file, update the version string before restarting OpenCode.

For source installs, pull the latest repo and re-run the installer:

```bash
cd memsearch
git pull
bash plugins/opencode/install.sh
```

## Uninstall

For npm installs, remove `@zilliz/memsearch-opencode` from the `plugin` array in `~/.config/opencode/opencode.json`, then restart OpenCode.

For source installs, remove the symlinks created by the installer:

```bash
rm -f ~/.config/opencode/plugins/memsearch.ts
rm -rf ~/.agents/skills/memory-recall
```

Uninstalling the plugin does not delete memory files in `.memsearch/memory/`.
