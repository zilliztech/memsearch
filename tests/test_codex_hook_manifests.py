from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins/claude-code"


def test_codex_manifest_selects_host_specific_hooks() -> None:
    manifest = json.loads((PACKAGE / ".codex-plugin/plugin.json").read_text())
    assert manifest["name"] == "memsearch"
    path = (PACKAGE / manifest["hooks"]).resolve()
    assert path.is_relative_to(PACKAGE.resolve())
    codex = json.loads(path.read_text())["hooks"]
    claude = json.loads((PACKAGE / "hooks/hooks.json").read_text())["hooks"]
    # Keep capture commands/timing identical; only exit timing is host-specific.
    expected = copy.deepcopy(claude)
    end = expected["SessionEnd"][0]["hooks"][0]
    assert end.pop("async") is True
    assert end["timeout"] == 10
    end["timeout"] = 3
    assert codex == expected
    assert codex["Stop"][0]["hooks"][0]["async"] is True


def test_marketplace_hooks_have_labels_and_existing_scripts() -> None:
    for filename in ("hooks.json", "hooks.codex.json"):
        hooks = json.loads((PACKAGE / "hooks" / filename).read_text())["hooks"]
        for groups in hooks.values():
            for group in groups:
                for hook in group["hooks"]:
                    assert hook["statusMessage"].strip().startswith("MemSearch:")
                    script = hook["command"].removeprefix("bash ${CLAUDE_PLUGIN_ROOT}/")
                    assert (PACKAGE / script).is_file()


def test_native_installer_labels_hooks_and_preserves_unrelated_entries(tmp_path: Path) -> None:
    # Exercise the installer's actual JSON writer without installing skills,
    # downloading packages, or editing the user's config.
    source = (ROOT / "plugins/codex/scripts/install.sh").read_text()
    function = source.split("install_or_update_hooks_file() {", 1)[1]
    writer = function.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    hooks_file = tmp_path / "hooks.json"
    unrelated = {"hooks": [{"type": "command", "command": "echo unrelated"}]}
    old = {"hooks": [{"type": "command", "command": "bash /old/plugins/codex/hooks/stop.sh"}]}
    hooks_file.write_text(json.dumps({"hooks": {"Stop": [unrelated, old]}}))
    install_dir = ROOT / "plugins/codex"
    command = [sys.executable, "-", str(hooks_file), str(install_dir)]
    subprocess.run(command, input=writer, text=True, check=True)
    first = hooks_file.read_text()
    subprocess.run(command, input=writer, text=True, check=True)
    assert hooks_file.read_text() == first
    hooks = json.loads(first)["hooks"]
    assert hooks["Stop"][0] == unrelated
    for event in ("SessionStart", "UserPromptSubmit", "Stop"):
        hook = hooks[event][-1]["hooks"][0]
        assert hook["statusMessage"].strip().startswith("MemSearch:")
        assert str(install_dir) in hook["command"]
