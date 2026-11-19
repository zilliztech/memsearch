"""Exercise native maintenance with real processes, including Windows npm shims."""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_maintenance_runner import _load_runner


@pytest.fixture
def native_cli(tmp_path, monkeypatch):
    directory = tmp_path / "cli with spaces"
    directory.mkdir()
    report = tmp_path / "received.json"
    script = directory / "capture.py"
    script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "if '--help' in sys.argv:\n"
        "    print('--safe-mode'); sys.exit(0)\n"
        "args = sys.argv[1:]\n"
        "prompt = sys.stdin.read()\n"
        "Path(os.environ['TEST_NATIVE_REPORT']).write_text(\n"
        "    json.dumps({'args': args, 'prompt': prompt}), encoding='utf-8')\n"
        "response = json.dumps({'action': 'none', 'reason': '已完成 😀'}, ensure_ascii=False)\n"
        "if '-o' in args:\n"
        "    Path(args[args.index('-o') + 1]).write_text(response, encoding='utf-8')\n"
        "    print('diagnostic output')\n"
        "else:\n"
        "    print(response)\n",
        encoding="utf-8",
    )
    for name in ("claude", "codex", "dsh"):
        if os.name == "nt":
            launcher = directory / f"{name}.cmd"
            launcher.write_text(f'@"{sys.executable}" -X utf8 "%~dp0capture.py" %*\n', encoding="utf-8")
        else:
            launcher = directory / name
            launcher.write_text(
                f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -X utf8 {shlex.quote(str(script))} "$@"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("TEST_NATIVE_REPORT", str(report))
    monkeypatch.delenv("DSH_CLI", raising=False)
    monkeypatch.delenv("MEMSEARCH_CODEX_PROFILE", raising=False)
    return directory, script, report


@pytest.mark.parametrize("platform", ["claude-code", "codex", "dsh"])
def test_native_cli_receives_long_unicode_prompt_on_stdin(native_cli, tmp_path, platform):
    runner = _load_runner()
    _, _, report = native_cli
    prompt = ('记忆 😀 "quoted" %PATH% !VALUE! ^ & | < >\n' * 2500) + "END"
    assert len(prompt) > 80_000
    ctx = SimpleNamespace(platform=platform, project_dir=tmp_path, task_config=SimpleNamespace(model=""))

    result = runner.run_native_provider(ctx, prompt)

    assert json.loads(result) == {"action": "none", "reason": "已完成 😀"}
    received = json.loads(report.read_text(encoding="utf-8"))
    assert received["prompt"] == prompt
    assert len(" ".join(received["args"])) < 2000
    if platform == "claude-code":
        assert "--safe-mode" in received["args"]
        assert received["args"][received["args"].index("--tools") + 1] == ""
    elif platform == "codex":
        assert received["args"][-1] == "-"
        assert not Path(received["args"][received["args"].index("-o") + 1]).exists()


@pytest.mark.parametrize("invocation", ["interpreter", "quoted_launcher", "bare_launcher"])
def test_dsh_custom_command_preserves_paths(native_cli, tmp_path, monkeypatch, invocation):
    runner = _load_runner()
    directory, script, report = native_cli
    if invocation == "interpreter":
        command = f'"{sys.executable}" -X utf8 "{script}"'
    elif invocation == "quoted_launcher":
        command = f'"{directory / ("dsh.cmd" if os.name == "nt" else "dsh")}"'
    else:
        command = "dsh"
    monkeypatch.setenv("DSH_CLI", command)
    ctx = SimpleNamespace(platform="dsh", project_dir=tmp_path, task_config=SimpleNamespace(model=""))
    assert json.loads(runner.run_native_provider(ctx, "custom invocation"))["action"] == "none"
    received = json.loads(report.read_text(encoding="utf-8"))
    assert received["prompt"] == "custom invocation"
    assert received["args"] == ["--profile", "headless"]


@pytest.mark.parametrize(
    "command,expected",
    [
        (r"C:\Users\Lin\dsh.cmd", [r"C:\Users\Lin\dsh.cmd"]),
        (r'"C:\Program Files\node.exe" "C:\DSH App\bin.js"', [r"C:\Program Files\node.exe", r"C:\DSH App\bin.js"]),
        (r'node "\\server\share\DSH App\bin.js"', ["node", r"\\server\share\DSH App\bin.js"]),
    ],
)
def test_dsh_windows_command_does_not_unescape_backslashes(monkeypatch, tmp_path, command, expected):
    runner = _load_runner()
    monkeypatch.setenv("DSH_CLI", command)
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt", environ=os.environ))
    captured = []

    def capture(args, **kwargs):
        captured.append(args)
        return '{"action":"none"}'

    monkeypatch.setattr(runner, "run_command", capture)
    ctx = SimpleNamespace(platform="dsh", project_dir=tmp_path, task_config=SimpleNamespace(model=""))
    runner.run_native_provider(ctx, "prompt")
    assert captured == [[*expected, "--profile", "headless"]]


def test_missing_native_cli_preserves_memory_and_allows_retry(tmp_path, monkeypatch, capsys):
    from memsearch.config import MemSearchConfig

    runner = _load_runner()
    memory = tmp_path / ".memsearch/memory"
    memory.mkdir(parents=True)
    (memory / "notes.md").write_text("- Preserve this synthetic memory.\n", encoding="utf-8")
    output = tmp_path / ".memsearch/PROJECT.md"
    output.write_text("Existing project memory.\n", encoding="utf-8")
    cfg = MemSearchConfig()
    cfg.plugins.dsh.project_review.enabled = True
    monkeypatch.setenv("DSH_CLI", "memsearch-nonexistent-native-test-executable")
    monkeypatch.setattr("memsearch.config.resolve_config", lambda: cfg)
    monkeypatch.setattr(sys, "argv", ["runner", "--platform", "dsh", "--project-dir", str(tmp_path)])
    assert runner.main() == 1
    assert "Maintenance error:" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "Existing project memory.\n"
    state_file = tmp_path / ".memsearch/.maintenance-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))["dsh.project_review"]
    assert "last_error" in state and "last_success_at" not in state
    runner.run_maintenance(
        "dsh",
        tmp_path,
        None,
        cfg,
        native_runner=lambda *_: '{"action":"none","reason":"retry succeeded"}',
    )
    assert json.loads(state_file.read_text(encoding="utf-8"))["dsh.project_review"]["last_success_at"]


def test_unread_long_stdin_still_times_out(tmp_path):
    import subprocess
    import time

    runner = _load_runner()
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run_command(
            [sys.executable, "-c", "import time; time.sleep(20)"],
            env=os.environ.copy(),
            cwd=tmp_path,
            timeout=0.2,
            input_text="大" * 80_000,
        )
    assert time.monotonic() - started < 10


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launcher")
def test_explicit_bat_launcher(native_cli, tmp_path):
    runner = _load_runner()
    directory, _, report = native_cli
    launcher = directory / "dsh.cmd"
    batch = launcher.with_suffix(".bat")
    launcher.rename(batch)
    runner.run_command([str(batch)], env=os.environ.copy(), cwd=tmp_path, timeout=10, input_text="记忆")
    assert json.loads(report.read_text(encoding="utf-8"))["prompt"] == "记忆"


def test_dsh_posix_escaped_path(native_cli, tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX shell escaping")
    runner = _load_runner()
    directory, _, report = native_cli
    command = str(directory / "dsh").replace(" ", r"\ ")
    monkeypatch.setenv("DSH_CLI", command)
    ctx = SimpleNamespace(platform="dsh", project_dir=tmp_path, task_config=SimpleNamespace(model=""))
    runner.run_native_provider(ctx, "POSIX")
    assert json.loads(report.read_text(encoding="utf-8"))["prompt"] == "POSIX"
