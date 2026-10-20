# Installation

## Compatibility

**Plugin 0.4.0 supports official OpenCode V2 `>=2.0.32 <3`.** Its development SDK is pinned to `@opencode/plugin@2.0.32`. V1 installations should keep the plugin pinned:

```json
{ "plugin": ["@zilliz/memsearch-opencode@0.3.17"] }
```

That singular `plugin` key is the V1 configuration. V2 uses `plugins`. Check the host version and actual loaded plugin path; comparing registry and worktree version strings alone is insufficient.

## Install the V2 plugin

Use the existing nvm Node 22 environment, Python 3.11+, and a current MemSearch CLI supporting `--default-collection`. Standalone TUI capture, fresh-session recall, L3 and exit recovery were validated with Node 22.23.2 on official CLI 2.0.32 and 2.1.0. Development types remain pinned to SDK 2.0.32. Install the core if needed:

```bash
uv tool install 'memsearch[onnx]'
```

Install the published package through OpenCode:

```bash
opencode plugin add @zilliz/memsearch-opencode@0.4.0
```

The equivalent V2 configuration is:

```json
{
  "plugins": ["@zilliz/memsearch-opencode@0.4.0"]
}
```

### Development source

From a source clone:

```bash
bash plugins/opencode/install.sh
```

The script installs source dependencies and prints the exact absolute entry to add to your V2 configuration. It does not edit shared host configuration, authentication, global Skills, or running daemons.

```json
{
  "plugins": ["/absolute/path/to/memsearch/plugins/opencode"]
}
```

Enable exactly one MemSearch source. Retain other plugins, but do not also enable an npm MemSearch package or an old `memsearch.ts` discovery link. All three Skills register at runtime with their packaged reference paths; no global Skill symlink is needed.

Restart and verify that OpenCode loaded this path and exposes the three memory tools. Memories live in the exact checkout's `.memsearch/memory/`. Explicit configured collections take precedence over the per-project derived fallback. Existing embedding/provider/model settings are preserved; the plugin never writes global config.

## Existing conversations

Follow the [official OpenCode migration guidance](https://opencode.ai/v2/docs/migrate-v1) yourself. MemSearch does not migrate the database or change Markdown anchors. First activation baselines already-settled history; it does not bulk-import old conversations. Existing journals remain searchable.

If L3 fails, check host/plugin compatibility, the anchor's database path, and the specific session/turn. A database with V2 tables may still lack a referenced migrated conversation. Keep useful search/expand results and report this limitation; do not reset capture state or rewrite anchors.

V1 can reject the V2 entrypoint before its Skills load. Use this page or an independently installed `memory-config` Skill for that diagnosis. Source tests and a published installation must be validated separately.
