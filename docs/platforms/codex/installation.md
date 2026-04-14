# Installation

## Prerequisites

- Codex CLI v0.116.0+
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

## Install

```bash
# 1. Clone the memsearch repo (if not already)
git clone https://github.com/zilliztech/memsearch.git

# 2. Run the installer
bash memsearch/plugins/codex/scripts/install.sh
```

The installer:

1. Copies the memory-recall skill to `~/.agents/skills/`
2. Installs or updates memsearch hooks in `~/.codex/hooks.json`
3. Enables `codex_hooks = true` in `~/.codex/config.toml`
4. Makes all scripts executable

## Usage

```bash
codex --dangerously-bypass-approvals-and-sandbox
```

!!! warning "Why full access?"
    Codex needs full access on the first run because the ONNX embedding model downloads from HuggingFace Hub (network access required). After the model is cached, full access is still the safest default because hooks execute shell commands. On current Codex builds, `--dangerously-bypass-approvals-and-sandbox` is the explicit full-access flag. Some builds may also accept the older `--yolo` alias.

## Pre-cache the Model (optional)

```bash
memsearch search "test" --collection test_warmup --provider onnx 2>/dev/null || true
```

---

## Configuration

### Embedding Provider

Default: `onnx` (bge-m3, CPU, no API key). Change with:

```bash
memsearch config set embedding.provider openai
export OPENAI_API_KEY="sk-..."
```

### Milvus Backend

Default: Milvus Lite (`~/.memsearch/milvus.db`). For remote Milvus:

```bash
memsearch config set milvus.uri http://localhost:19530
```

---

## Uninstall

```bash
python3 - <<'PY'
from pathlib import Path
import json
import shutil

skill_dir = Path.home() / ".agents/skills/memory-recall"
if skill_dir.is_symlink() or skill_dir.is_file():
    skill_dir.unlink()
elif skill_dir.exists():
    shutil.rmtree(skill_dir)

hooks_file = Path.home() / ".codex/hooks.json"
markers = {
    "SessionStart": "plugins/codex/hooks/session-start.sh",
    "UserPromptSubmit": "plugins/codex/hooks/user-prompt-submit.sh",
    "Stop": "plugins/codex/hooks/stop.sh",
}

if hooks_file.exists():
    data = json.loads(hooks_file.read_text())
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    for event, marker in markers.items():
        kept_entries = []
        for entry in hooks.get(event, []):
            if not isinstance(entry, dict):
                continue
            kept_hooks = []
            for hook in entry.get("hooks", []):
                command = hook.get("command", "") if isinstance(hook, dict) else ""
                if marker not in command:
                    kept_hooks.append(hook)
            if kept_hooks:
                updated = dict(entry)
                updated["hooks"] = kept_hooks
                kept_entries.append(updated)
        if kept_entries:
            hooks[event] = kept_entries
        else:
            hooks.pop(event, None)
    if hooks:
        data["hooks"] = hooks
        hooks_file.write_text(json.dumps(data, indent=2) + "\\n")
    else:
        hooks_file.unlink()
PY

# Optionally disable hooks in ~/.codex/config.toml if you have no other hooks.
# Optionally remove memsearch itself:
uv tool uninstall memsearch
```

## Updating

```bash
# Update memsearch
uv tool upgrade memsearch

# Re-run installer to update hooks and skill
bash memsearch/plugins/codex/scripts/install.sh
```
