from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from memsearch.config import LLMProviderConfig, MemSearchConfig, PluginMaintenanceTaskConfig
from memsearch.maintenance import TaskContext, _read_recent_journals, run_due_tasks, run_memory_command, run_task_llm


def test_maintenance_routes_gemini_provider_to_tool_runner(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-05-27.md").write_text("- User discussed Gemini maintenance.\n", encoding="utf-8")

    cfg = MemSearchConfig()
    cfg.llm.providers["gemini"] = LLMProviderConfig(type="gemini", model="gemini-test")
    cfg.plugins.codex.project_review.enabled = True
    cfg.plugins.codex.project_review.provider = "gemini"

    captured = {}

    def fake_gemini(ctx, prompt: str, model: str | None, provider_cfg) -> str:
        captured["model"] = model
        captured["provider_type"] = provider_cfg.type
        return json.dumps({"action": "none", "reason": "ok"})

    monkeypatch.setattr("memsearch.maintenance._run_gemini_with_tools", fake_gemini)

    results = run_due_tasks(platform="codex", project_dir=project, cfg=cfg)

    assert results[0].action == "none"
    assert captured == {"model": "gemini-test", "provider_type": "gemini"}


def test_read_recent_journals_replaces_invalid_utf8_bytes(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "2026-06-09.md").write_bytes(b"### 10:00\n- broken \xff byte\n")

    journals = _read_recent_journals(memory)

    assert "<!-- source:" in journals
    assert "broken \ufffd byte" in journals


def test_openai_maintenance_uses_default_temperature(tmp_path: Path, monkeypatch) -> None:
    from memsearch import maintenance as maintenance_module

    captured: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content='{"action":"none","reason":"ok"}', tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    ctx = TaskContext(
        platform="codex",
        task="project_review",
        task_config=PluginMaintenanceTaskConfig(),
        project_dir=project,
        memsearch_dir=project / ".memsearch",
        input_dir=memory,
        output_file=project / ".memsearch" / "PROJECT.md",
        input_digest="sha256:test",
    )

    result = maintenance_module._run_openai_with_tools(
        ctx,
        "prompt",
        "openai",
        "gpt-5-mini",
        LLMProviderConfig(type="openai"),
    )

    assert result == '{"action":"none","reason":"ok"}'
    assert captured["model"] == "gpt-5-mini"
    assert captured["tool_choice"] == "auto"
    assert "temperature" not in captured


def test_maintenance_replace_writes_output_and_state(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-05-27.md").write_text("### 10:00\n- User discussed maintenance runner.\n", encoding="utf-8")

    cfg = MemSearchConfig()
    cfg.plugins.codex.project_review.enabled = True
    cfg.plugins.codex.project_review.provider = "openai"

    def fake_runner(ctx, prompt: str) -> str:
        assert "Recent memory journal entries" in prompt
        return json.dumps(
            {
                "action": "replace",
                "reason": "new project state",
                "content": "# Project Memory\n\n## Active Threads\n- Maintenance runner.",
            }
        )

    results = run_due_tasks(platform="codex", project_dir=project, cfg=cfg, llm_runner=fake_runner)

    assert [r.action for r in results] == ["replace", "disabled"]
    assert (project / ".memsearch" / "PROJECT.md").read_text(encoding="utf-8").startswith("# Project Memory")
    state = json.loads((project / ".memsearch" / ".maintenance-state.json").read_text(encoding="utf-8"))
    assert state["codex.project_review"]["last_action"] == "replace"
    assert state["codex.project_review"]["last_input_digest"].startswith("sha256:")


def test_maintenance_skips_unchanged_input(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-05-27.md").write_text("### 10:00\n- Stable note.\n", encoding="utf-8")

    cfg = MemSearchConfig()
    cfg.plugins.codex.project_review.enabled = True

    calls = 0

    def fake_runner(ctx, prompt: str) -> str:
        nonlocal calls
        calls += 1
        return json.dumps({"action": "none", "reason": "no durable change"})

    first = run_due_tasks(platform="codex", project_dir=project, cfg=cfg, llm_runner=fake_runner)
    second = run_due_tasks(platform="codex", project_dir=project, cfg=cfg, llm_runner=fake_runner)

    assert first[0].action == "none"
    assert second[0].action == "skip"
    assert calls == 1


def test_run_memory_command_rejects_shell_metacharacters(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    input_dir = project / ".memsearch" / "memory"
    input_dir.mkdir(parents=True)
    cfg = MemSearchConfig()
    cfg.plugins.codex.project_review.enabled = True

    captured = {}

    def fake_runner(ctx, prompt: str) -> str:
        captured["ctx"] = ctx
        return json.dumps({"action": "none", "reason": "test"})

    run_due_tasks(platform="codex", project_dir=project, cfg=cfg, force=True, llm_runner=fake_runner)
    output = run_memory_command("cat /etc/passwd", captured["ctx"])

    assert "not allowed" in output


def test_native_provider_requires_plugin_runner(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    input_dir = project / ".memsearch" / "memory"
    input_dir.mkdir(parents=True)
    cfg = MemSearchConfig()
    cfg.plugins.codex.project_review.enabled = True
    cfg.plugins.codex.project_review.provider = "native"

    captured = {}

    def fake_runner(ctx, prompt: str) -> str:
        captured["ctx"] = ctx
        return json.dumps({"action": "none", "reason": "test"})

    run_due_tasks(platform="codex", project_dir=project, cfg=cfg, force=True, llm_runner=fake_runner)

    try:
        run_task_llm(captured["ctx"], "{}", cfg)
    except RuntimeError as e:
        assert "plugin runner" in str(e)
    else:
        raise AssertionError("native maintenance provider should require plugin runner")
