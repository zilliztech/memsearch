from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "posix", reason="tests the POSIX shell-form hook launcher")
@pytest.mark.parametrize(
    "directory",
    [
        "checkout",
        "checkout with spaces",
        "checkout\twith\ttabs",
        "checkout's cache",
        'checkout "cache"',
        'checkout\'s "$HOME"; [cache]',
        "pl$HOMEx",
        "checkout-`printf EXPANDED`",
        "checkout-$(printf EXPANDED)",
        "checkout\\cache",
        "checkout;cache",
        "checkout&cache",
        "checkout|cache",
        "checkout<cache>",
        "checkout*[cache]?",
        "checkout\ncache",
        "checkout!cache",
        "缓存",
    ],
)
@pytest.mark.parametrize("existing_format", ["missing", "object", "legacy"])
def test_codex_installer_quotes_hook_paths_and_preserves_existing_hooks(
    tmp_path: Path, directory: str, existing_format: str
) -> None:
    plugin_root = tmp_path / directory / "plugins" / "codex"
    shutil.copytree(Path("plugins/codex"), plugin_root)
    scripts = {
        "SessionStart": "session-start.sh",
        "UserPromptSubmit": "user-prompt-submit.sh",
        "Stop": "stop.sh",
    }
    # The real installer generates commands. Inert hook bodies prove which file
    # is launched without starting watchers, installing dependencies, or using
    # models. This is not a native Codex lifecycle/integration test.
    for script in scripts.values():
        (plugin_root / "hooks" / script).write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n%s\\n" "${BASH_SOURCE[0]}" "$#"\n', encoding="utf-8"
        )

    home = tmp_path / "home"
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    memsearch = fake_bin / "memsearch"
    memsearch.write_text('#!/bin/sh\nprintf "memsearch test\\n"\n', encoding="utf-8")
    memsearch.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}

    unrelated = {"type": "command", "command": "echo unrelated", "timeout": 7}
    existing = {"description": "Keep this configuration", "hooks": {}}
    for event, script in scripts.items():
        # Replace both historical unquoted and already-quoted memsearch entries
        # without losing another hook in the same matcher group.
        existing["hooks"][event] = [
            {
                "matcher": "preserve-me",
                "hooks": [
                    unrelated,
                    {"type": "command", "command": f"bash /old/plugins/codex/hooks/{script}"},
                    {"type": "command", "command": f'bash "/old path/plugins/codex/hooks/{script}"'},
                ],
            }
        ]
    hooks_file = codex_dir / "hooks.json"
    if existing_format == "object":
        hooks_file.write_text(json.dumps(existing), encoding="utf-8")
    elif existing_format == "legacy":
        legacy = []
        for event, script in scripts.items():
            legacy.extend(
                [
                    {"event": event, "command": unrelated["command"], "matcher": "preserve-me", "timeout_ms": 7000},
                    {"event": event, "command": f"bash /old/plugins/codex/hooks/{script}"},
                ]
            )
        hooks_file.write_text(json.dumps(legacy), encoding="utf-8")

    previous = None
    for _ in range(2):
        result = subprocess.run(
            ["bash", str(plugin_root / "scripts" / "install.sh")],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        installed = json.loads(hooks_file.read_text(encoding="utf-8"))
        if existing_format == "object":
            assert installed["description"] == existing["description"]
        assert set(installed["hooks"]) == set(scripts)
        for event, script in scripts.items():
            entries = installed["hooks"][event]
            assert len(entries) == (1 if existing_format == "missing" else 2)
            if existing_format != "missing":
                assert entries[0] == {"matcher": "preserve-me", "hooks": [unrelated]}
            assert entries[-1]["matcher"] == ""
            assert len(entries[-1]["hooks"]) == 1
            hook = entries[-1]["hooks"][0]
            assert hook["type"] == "command"
            assert hook["timeout"] == (10 if event == "UserPromptSubmit" else 30)
            command = hook["command"]
            for shell in ("sh", "bash"):
                launched = subprocess.run(
                    [shell, "-lc", command],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=tmp_path,
                    timeout=10,
                    check=False,
                )
                assert launched.returncode == 0, launched.stderr
                assert launched.stdout == f"{plugin_root / 'hooks' / script}\n0\n"
                assert launched.stderr == ""
        if previous is not None:
            assert installed == previous
        previous = installed
