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
    assert captured["env"]["MEMSEARCH_DISABLE"] == "1"
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


@pytest.mark.parametrize("provider", ["native", "managed"])
def test_opencode_maintenance_uses_injected_native_or_shared_api(tmp_path, monkeypatch, provider):
    from memsearch import maintenance
    from memsearch.config import MemSearchConfig

    runner = _load_runner()
    cfg = MemSearchConfig()
    cfg.plugins.opencode.project_review.enabled = True
    cfg.plugins.opencode.project_review.provider = provider
    cfg.plugins.opencode.project_review.model = "task-model"
    memory = tmp_path / ".memsearch/memory"
    memory.mkdir(parents=True)
    (memory / "2026-10-20.md").write_text("- Durable project decision: synthetic test.\n")
    calls = []

    def reply(ctx, prompt):
        calls.append((ctx.task, ctx.task_config.model))
        assert "synthetic test" in prompt
        return json.dumps(
            {"action": "replace", "reason": "test", "content": "# Project Memory\n\n- Synthetic decision."}
        )

    def native(ctx, prompt):
        assert provider == "native"
        return reply(ctx, prompt)

    def managed(ctx, prompt, config):
        assert provider == "managed" and config is cfg
        return reply(ctx, prompt)

    monkeypatch.setattr(maintenance, "run_task_llm", managed)
    runner.run_maintenance("opencode", tmp_path, str(tmp_path / ".memsearch"), cfg, native_runner=native)
    assert calls == [("project_review", "task-model")]
    assert "Synthetic decision" in (tmp_path / ".memsearch/PROJECT.md").read_text()
    runner.run_maintenance("opencode", tmp_path, str(tmp_path / ".memsearch"), cfg, native_runner=native)
    assert len(calls) == 1  # Shared input digest / due-state retained.


def test_opencode_cli_native_requires_live_callback(tmp_path):
    runner = _load_runner()
    ctx = SimpleNamespace(platform="opencode", project_dir=tmp_path, task_config=SimpleNamespace(model=""))
    with pytest.raises(RuntimeError, match="generation callback"):
        runner.run_native_provider(ctx, "prompt")


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
