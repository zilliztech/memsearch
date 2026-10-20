from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "plugins" / "_shared" / "scripts" / "maintenance-runner.py"
    spec = importlib.util.spec_from_file_location("memsearch_plugin_maintenance_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_maintenance_runner_copies_match_shared() -> None:
    root = Path(__file__).resolve().parents[1]
    shared = (root / "plugins" / "_shared" / "scripts" / "maintenance-runner.py").read_text(encoding="utf-8")
    for platform in ["claude-code", "codex", "openclaw", "opencode", "dsh"]:
        copied = (root / "plugins" / platform / "scripts" / "maintenance-runner.py").read_text(encoding="utf-8")
        assert copied == shared


def test_plugin_maintenance_runner_uses_global_config(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-05-28.md").write_text("- Project decision: test shared runner.\n", encoding="utf-8")
    from memsearch import config as config_module

    global_cfg = tmp_path / "global.toml"
    monkeypatch.setattr(config_module, "GLOBAL_CONFIG_PATH", global_cfg)
    config_module.save_config(
        {"plugins": {"codex": {"project_review": {"enabled": True, "provider": "native"}}}},
        global_cfg,
    )

    def fake_native(ctx, prompt: str) -> str:
        assert ctx.project_dir == project
        assert "test shared runner" in prompt
        return json.dumps(
            {
                "action": "replace",
                "reason": "test",
                "content": "# Project Memory\n\n## Decisions\n- Test shared runner.",
            }
        )

    monkeypatch.setattr(runner, "run_native_provider", fake_native)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maintenance-runner.py",
            "--platform",
            "codex",
            "--project-dir",
            str(project),
            "--json-output",
        ],
    )

    assert runner.main() == 0
    assert (project / ".memsearch" / "PROJECT.md").read_text(encoding="utf-8").startswith("# Project Memory")


def test_codex_native_runner_uses_profile_and_last_message(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    captured = {}

    def fake_run_command(cmd, *, env, cwd, timeout):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["cwd"] = cwd
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text('{"action":"none","reason":"ok"}', encoding="utf-8")
        return "diagnostic output that is not JSON"

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    monkeypatch.setenv("MEMSEARCH_CODEX_PROFILE", "zilliz")

    ctx = SimpleNamespace(
        platform="codex",
        project_dir=tmp_path,
        task_config=SimpleNamespace(model=""),
    )

    result = runner.run_native_provider(ctx, "prompt")

    assert json.loads(result) == {"action": "none", "reason": "ok"}
    assert captured["cmd"][0:2] == ["codex", "exec"]
    assert captured["cmd"][captured["cmd"].index("-p") + 1] == "zilliz"
    assert "-o" in captured["cmd"]
    assert "features.hooks=false" in captured["cmd"]
    assert captured["env"]["MEMSEARCH_IN_STOP_WORKER"] == "1"


def test_claude_native_runner_passes_prompt_as_user_input(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    captured = {}

    def fake_run_command(cmd, *, env, cwd, timeout, input=None):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["cwd"] = cwd
        captured["input"] = input
        return '{"action":"none","reason":"ok"}'

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    ctx = SimpleNamespace(
        platform="claude-code",
        project_dir=tmp_path,
        task_config=SimpleNamespace(model="sonnet"),
    )

    result = runner.run_native_provider(ctx, "maintenance prompt")

    assert json.loads(result) == {"action": "none", "reason": "ok"}
    assert captured["env"]["MEMSEARCH_DISABLE"] == "1"
    assert captured["cmd"][0:2] == ["claude", "-p"]
    assert captured["input"] == "maintenance prompt"
    assert "maintenance prompt" not in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--system-prompt") + 1] != "maintenance prompt"
    assert captured["env"]["CLAUDECODE"] == ""


def test_claude_native_runner_keeps_long_prompts_off_the_command_line(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    captured = {}

    def fake_run_command(cmd, *, env, cwd, timeout, input=None):
        captured["cmd"] = cmd
        captured["input"] = input
        return '{"action":"none","reason":"ok"}'

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    ctx = SimpleNamespace(platform="claude-code", project_dir=tmp_path, task_config=SimpleNamespace(model=""))
    prompt = "journal line → åäö\n" * 8000

    runner.run_native_provider(ctx, prompt)

    assert captured["input"] == prompt
    assert sum(len(arg) + 1 for arg in captured["cmd"]) < 32767


def test_openclaw_native_runner_extracts_json_from_noisy_output(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()

    def fake_run_command(cmd, *, env, cwd, timeout):
        return "\n".join(
            [
                "[plugins] [memsearch] Plugin loaded.",
                '{"action":"none","reason":"ok"}',
                "[plugins] [memsearch] Captured turn summary.",
            ]
        )

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    ctx = SimpleNamespace(
        platform="openclaw",
        project_dir=tmp_path,
        task_config=SimpleNamespace(model=""),
    )

    result = runner.run_native_provider(ctx, "maintenance prompt")

    assert json.loads(result) == {"action": "none", "reason": "ok"}


def test_opencode_native_runner_uses_sanitized_isolated_config(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    home = tmp_path / "home"
    project = tmp_path / "repo"
    config_dir = tmp_path / "opencode-config-dir"
    home.mkdir()
    project.mkdir()
    config_dir.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() reads this on Windows
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"username": "from-content", "plugin": ["content-plugin"]}')
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_DISABLE_PROJECT_CONFIG", raising=False)

    (project / "opencode.jsonc").write_text(
        '{"model": "project/model", "plugin": ["project-plugin"]}',
        encoding="utf-8",
    )
    (config_dir / "opencode.jsonc").write_text(
        '{"model": "dir/model", "provider": {"openai": {"apiKey": "{file:token.txt}"}}, "plugin": ["dir-plugin"]}',
        encoding="utf-8",
    )

    captured = {}

    def fake_run_command(cmd, *, env, cwd, timeout):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["cwd"] = cwd
        return '{"action":"none","reason":"ok"}'

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    ctx = SimpleNamespace(
        platform="opencode",
        project_dir=project,
        task_config=SimpleNamespace(model=""),
    )

    result = runner.run_native_provider(ctx, "maintenance prompt")

    isolated_root = home / ".codex" / "tmp" / "opencode-memsearch-maintenance"
    isolated_config = json.loads((isolated_root / "opencode" / "opencode.json").read_text(encoding="utf-8"))

    assert json.loads(result) == {"action": "none", "reason": "ok"}
    assert captured["cmd"] == ["opencode", "run", "maintenance prompt"]
    assert captured["cwd"] == project
    assert captured["env"]["XDG_CONFIG_HOME"] == str(isolated_root)
    assert captured["env"]["XDG_DATA_HOME"] == str(isolated_root / "data")
    assert captured["env"]["OPENCODE_CONFIG"] == ""
    assert captured["env"]["OPENCODE_CONFIG_DIR"] == ""
    assert captured["env"]["OPENCODE_CONFIG_CONTENT"] == ""
    assert captured["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"
    assert captured["env"]["MEMSEARCH_NO_WATCH"] == "1"
    assert isolated_config["model"] == "dir/model"
    assert isolated_config["username"] == "from-content"
    assert isolated_config["provider"]["openai"]["apiKey"] == f"{{file:{config_dir / 'token.txt'}}}"
    assert "plugin" not in isolated_config


def test_dsh_native_runner_uses_headless_profile_and_dsh_cli(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    captured = {}

    def fake_run_command(cmd, *, env, cwd, timeout):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["cwd"] = cwd
        return '{"action":"none","reason":"ok"}'

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    monkeypatch.setenv("DSH_CLI", "node /opt/dsh/bin.js --flag")
    ctx = SimpleNamespace(
        platform="dsh",
        project_dir=tmp_path,
        task_config=SimpleNamespace(model=""),
    )

    result = runner.run_native_provider(ctx, "maintenance prompt")

    assert json.loads(result) == {"action": "none", "reason": "ok"}
    assert captured["cmd"] == ["node", "/opt/dsh/bin.js", "--flag", "--profile", "headless", "maintenance prompt"]
    assert captured["cwd"] == tmp_path
    assert captured["env"]["DSH_CLI"] == "node /opt/dsh/bin.js --flag"
    assert captured["env"]["MEMSEARCH_DSH_SUMMARIZE"] == "1"  # plugin inert inside the sub-agent
    assert captured["env"]["MEMSEARCH_DISABLE"] == "1"


def test_dsh_native_runner_defaults_to_plain_dsh_command(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    captured = {}

    def fake_run_command(cmd, *, env, cwd, timeout):
        captured["cmd"] = cmd
        return '{"action":"none","reason":"ok"}'

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    monkeypatch.delenv("DSH_CLI", raising=False)
    ctx = SimpleNamespace(
        platform="dsh",
        project_dir=tmp_path,
        task_config=SimpleNamespace(model=""),
    )

    result = runner.run_native_provider(ctx, "maintenance prompt")

    assert json.loads(result) == {"action": "none", "reason": "ok"}
    assert captured["cmd"] == ["dsh", "--profile", "headless", "maintenance prompt"]


def test_run_command_raises_with_exit_details(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["tool"], returncode=2, stdout="partial output", stderr="bad credentials"
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        runner.run_command(["tool", "run", "x" * 200], env={}, cwd=tmp_path, timeout=1)

    message = str(exc_info.value)
    assert "Command failed (2): tool run '<arg:200 chars>'" in message
    assert "partial output" in message
    assert "bad credentials" in message
    assert "x" * 120 not in message


def test_run_command_success_prefers_stdout(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["tool"], returncode=0, stdout='{"ok": true}', stderr="warning")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.run_command(["tool"], env={}, cwd=tmp_path, timeout=1) == '{"ok": true}'


def test_run_command_resolves_executable_on_path_and_sends_utf8_input(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    seen = {}

    def fake_which(name, path=None):
        seen["which"] = (name, path)
        return r"C:\Users\me\AppData\Roaming\npm\claude.CMD"

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(runner.shutil, "which", fake_which)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    out = runner.run_command(["claude", "-p"], env={"PATH": "/fake/bin"}, cwd=tmp_path, timeout=1, input="→ prompt")

    assert out == '{"ok": true}'
    assert seen["which"] == ("claude", "/fake/bin")
    assert seen["cmd"] == [r"C:\Users\me\AppData\Roaming\npm\claude.CMD", "-p"]
    assert seen["kwargs"]["input"] == "→ prompt"
    assert seen["kwargs"]["encoding"] == "utf-8"


def test_run_command_passes_unresolvable_names_through(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(runner.shutil, "which", lambda name, path=None: None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_command(["tool", "run"], env={"PATH": ""}, cwd=tmp_path, timeout=1)

    assert seen["cmd"] == ["tool", "run"]


def test_run_command_passes_utf8_prompt_through_a_real_process(tmp_path: Path) -> None:
    runner = _load_runner()
    import os

    prompt = "journal → åäö \U0001f4da\n" * 5000
    script = (
        "import hashlib, sys; "
        "data = sys.stdin.buffer.read().decode('utf-8').replace('\\r\\n', '\\n'); "
        "print(hashlib.sha256(data.encode('utf-8')).hexdigest())"
    )

    out = runner.run_command(
        [sys.executable, "-c", script], env=dict(os.environ), cwd=tmp_path, timeout=30, input=prompt
    )

    import hashlib

    assert out == hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def test_main_still_distills_skills_when_a_review_task_fails(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    project = tmp_path / "repo"
    (project / ".memsearch" / "memory").mkdir(parents=True)
    from memsearch import maintenance, skills

    def failing_tasks(**kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    distilled = {}

    def fake_distill(**kwargs):
        distilled["called"] = True
        return SimpleNamespace(action="skip", reason="not due")

    monkeypatch.setattr(maintenance, "run_due_tasks", failing_tasks)
    monkeypatch.setattr(skills, "distill", fake_distill)
    monkeypatch.setattr(
        sys, "argv", ["maintenance-runner.py", "--platform", "claude-code", "--project-dir", str(project)]
    )

    assert runner.main() == 1
    assert distilled["called"] is True
