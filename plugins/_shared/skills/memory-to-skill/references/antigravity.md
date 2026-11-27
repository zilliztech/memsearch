# Antigravity

Use `plugins.antigravity.memory_to_skill.*`. Background distillation is disabled
by default; it honors `provider`, `model`, `min_interval_hours`, `input_dir`,
`min_occurrences`, and `paths` through the shared core.

Run candidate CLI commands through `scripts/runtime.py cli --project-dir
/absolute/workspace -- skills ...` from this plugin. The runtime uses the
workspace's memory root, including `MEMSEARCH_DIR`. Native background
distillation can request up to three read-only transcript/expand commands
through the shared bridge. The adapter validates anchored transcript paths
and turns, keeps expand in the workspace collection, and returns bounded
results for the next model response. The helper has no general tools or
inherited customizations. `.antigravity/native-maintenance/memory_to_skill.json`
records bounded request metadata and result hashes without duplicating raw
transcripts. Review source anchors to verify the candidate's exact commands.

Inspect the candidate before installation. The usual workspace destination is
`.agents/skills`; use configured or user-approved paths and start a new
Antigravity session after installation. Candidate generation never installs a
skill automatically.
