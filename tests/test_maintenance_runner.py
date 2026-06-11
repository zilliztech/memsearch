from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


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
    for platform in ["claude-code", "codex", "openclaw", "opencode"]:
        copied = (root / "plugins" / platform / "scripts" / "maintenance-runner.py").read_text(encoding="utf-8")
        assert copied == shared


def test_plugin_maintenance_runner_uses_project_config(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-05-28.md").write_text("- Project decision: test shared runner.\n", encoding="utf-8")
    (project / ".memsearch.toml").write_text(
        '[plugins.codex.project_review]\nenabled = true\nprovider = "native"\n',
        encoding="utf-8",
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
    assert captured["env"]["MEMSEARCH_IN_STOP_WORKER"] == "1"


def test_claude_native_runner_passes_prompt_as_user_input(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    captured = {}

    def fake_run_command(cmd, *, env, cwd, timeout):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["cwd"] = cwd
        return '{"action":"none","reason":"ok"}'

    monkeypatch.setattr(runner, "run_command", fake_run_command)
    ctx = SimpleNamespace(
        platform="claude-code",
        project_dir=tmp_path,
        task_config=SimpleNamespace(model="sonnet"),
    )

    result = runner.run_native_provider(ctx, "maintenance prompt")

    assert json.loads(result) == {"action": "none", "reason": "ok"}
    assert captured["cmd"][0:2] == ["claude", "-p"]
    assert captured["cmd"][-1] == "maintenance prompt"
    assert captured["cmd"][captured["cmd"].index("--system-prompt") + 1] != "maintenance prompt"
    assert captured["env"]["CLAUDECODE"] == ""


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
    assert isolated_config["model"] == "dir/model"
    assert isolated_config["username"] == "from-content"
    assert isolated_config["provider"]["openai"]["apiKey"] == f"{{file:{config_dir / 'token.txt'}}}"
    assert "plugin" not in isolated_config
