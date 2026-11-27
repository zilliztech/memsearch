from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from memsearch import maintenance
from memsearch.config import LLMProviderConfig, MemSearchConfig, PluginMaintenanceTaskConfig
from memsearch.maintenance import (
    MAX_PROMPT_CHARS,
    TaskContext,
    _build_prompt,
    _parse_task_response,
    _read_recent_journals,
    run_due_tasks,
    run_memory_command,
    run_task_llm,
)


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


def test_anthropic_tool_runner_defaults_to_current_sonnet(tmp_path: Path, monkeypatch) -> None:
    """The Anthropic tool runner falls back to the current default Sonnet model."""
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))

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
        output_file=project / "PROJECT.md",
        input_digest="sha256:test",
    )

    result = maintenance._run_anthropic_with_tools(ctx, "prompt", None, LLMProviderConfig())

    assert result == "ok"
    assert captured == {"model": "claude-sonnet-5-5"}


@pytest.mark.parametrize("model", [None, "claude-sonnet-5-5", "claude-sonnet-4-6", "custom-model"])
def test_anthropic_tool_limit_preserves_thinking_history(monkeypatch, model) -> None:
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    requests = []
    thinking = {"type": "thinking", "thinking": "", "signature": "test-signature"}

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        content = [{"type": "text", "text": "review complete"}]
        stop_reason = "end_turn"
        if len(requests) <= maintenance.MAX_TOOL_CALLS:
            content = [
                thinking,
                {
                    "type": "tool_use",
                    "id": f"tool_{len(requests)}",
                    "name": "run_memory_command",
                    "input": {"command": "memsearch search marker"},
                },
            ]
            stop_reason = "tool_use"
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        )

    with anthropic.Anthropic(
        api_key="test-key",
        base_url="https://example.invalid",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        monkeypatch.setattr(anthropic, "Anthropic", lambda: client)
        monkeypatch.setattr(maintenance, "run_memory_command", lambda command, ctx: "memory result")
        result = maintenance._run_anthropic_with_tools(SimpleNamespace(), "Review memories", model, LLMProviderConfig())

    assert result == "review complete"
    assert len(requests) == maintenance.MAX_TOOL_CALLS + 1
    for index, body in enumerate(requests):
        assert body["model"] == (model or "claude-sonnet-5-5")
        assert "thinking" not in body
        if index:
            previous = requests[index - 1]["messages"]
            assert body["messages"][:-2] == previous
            assistant, user = body["messages"][-2:]
            assert assistant["content"][0] == thinking
            assert user["content"] == [
                {"type": "tool_result", "tool_use_id": f"tool_{index}", "content": "memory result"}
            ]
    closing = requests[-1]
    if model in (None, "claude-sonnet-5-5"):
        assert all(body["tools"] == requests[0]["tools"] for body in requests)
        assert closing["tool_choice"] == {"type": "none"}
    else:
        assert "tools" not in closing
        assert "tool_choice" not in closing


def test_read_recent_journals_replaces_invalid_utf8_bytes(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "2026-06-09.md").write_bytes(b"### 10:00\n- broken \xff byte\n")

    journals = _read_recent_journals(memory)

    assert "<!-- source:" in journals
    assert "broken \ufffd byte" in journals


def test_read_recent_journals_respects_max_files(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()

    oldest = memory / "2026-07-25.md"
    middle = memory / "2026-07-26.md"
    newest = memory / "2026-07-27.md"

    oldest.write_text("OLDEST_JOURNAL_MARKER\n", encoding="utf-8")
    middle.write_text("MIDDLE_JOURNAL_MARKER\n", encoding="utf-8")
    newest.write_text("NEWEST_JOURNAL_MARKER\n", encoding="utf-8")

    os.utime(oldest, (100, 100))
    os.utime(middle, (200, 200))
    os.utime(newest, (300, 300))

    journals = _read_recent_journals(memory, max_files=2)

    assert "NEWEST_JOURNAL_MARKER" in journals
    assert "MIDDLE_JOURNAL_MARKER" in journals
    assert "OLDEST_JOURNAL_MARKER" not in journals
    assert journals.index("MIDDLE_JOURNAL_MARKER") < journals.index("NEWEST_JOURNAL_MARKER")


def test_build_prompt_preserves_newest_journal_when_corpus_exceeds_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)

    oldest = memory / "2026-07-26.md"
    newest = memory / "2026-07-27.md"

    oldest.write_text(
        "OLDEST_JOURNAL_MARKER\n" + "x" * (MAX_PROMPT_CHARS + 1_000),
        encoding="utf-8",
    )
    newest.write_text(
        "NEWEST_JOURNAL_MARKER\n",
        encoding="utf-8",
    )

    os.utime(oldest, (100, 100))
    os.utime(newest, (200, 200))

    monkeypatch.setattr(
        "memsearch.maintenance._load_prompt_template",
        lambda task, cfg: "Maintenance prompt",
    )

    ctx = TaskContext(
        platform="claude-code",
        task="project_review",
        task_config=PluginMaintenanceTaskConfig(),
        project_dir=project,
        memsearch_dir=project / ".memsearch",
        input_dir=memory,
        output_file=project / ".memsearch" / "PROJECT.md",
        input_digest="sha256:test",
    )

    prompt = _build_prompt(ctx, MemSearchConfig())

    assert "NEWEST_JOURNAL_MARKER" in prompt
    assert "OLDEST_JOURNAL_MARKER" not in prompt
    assert "[older journal entries truncated]" in prompt
    assert len(prompt) <= MAX_PROMPT_CHARS


def test_newest_entries_within_oversized_journal_survive(
    tmp_path: Path,
) -> None:
    memory = tmp_path / ".memsearch" / "memory"
    memory.mkdir(parents=True)

    journal = memory / "2026-07-28.md"
    journal.write_text(
        "### 09:00\nEARLIEST_ENTRY_MARKER\n" + "filler\n" * 1_000 + "### 23:00\nLATEST_ENTRY_MARKER\n",
        encoding="utf-8",
    )

    os.utime(journal, (200, 200))

    budget = 512
    journals = _read_recent_journals(
        memory,
        budget=budget,
    )

    assert "LATEST_ENTRY_MARKER" in journals
    assert "EARLIEST_ENTRY_MARKER" not in journals
    assert "[older journal entries truncated]" in journals
    assert len(journals) <= budget


@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"none","reason":"ok"}',
        '```json\n{"action":"none","reason":"ok"}\n```',
    ],
)
def test_parse_task_response_preserves_supported_json_formats(raw: str) -> None:
    assert _parse_task_response(raw) == {
        "action": "none",
        "reason": "ok",
    }


def test_parse_task_response_accepts_reasoning_before_json() -> None:
    raw = """\
## Reasoning
The recent journals do not add durable project state.

## Result
{"action":"none","reason":"No durable change."}
"""

    assert _parse_task_response(raw) == {
        "action": "none",
        "reason": "No durable change.",
    }


@pytest.mark.parametrize(
    "suffix",
    [
        '"',
        "\n\nDone.",
    ],
)
def test_parse_task_response_accepts_trailing_text_after_json(
    suffix: str,
) -> None:
    raw = '{"action":"none","reason":"ok"}' + suffix

    assert _parse_task_response(raw) == {
        "action": "none",
        "reason": "ok",
    }


def test_parse_task_response_skips_invalid_braces_before_result() -> None:
    raw = """\
Reasoning mentioned {not valid JSON}.

{"action":"none","reason":"ok"}
"""

    assert _parse_task_response(raw) == {
        "action": "none",
        "reason": "ok",
    }


def test_parse_task_response_prefers_final_maintenance_object() -> None:
    raw = """\
The expected no-op shape is {"action":"none","reason":"example"}.

## Result
{"action":"replace","reason":"durable update","content":"# Project Memory"}
"""

    assert _parse_task_response(raw) == {
        "action": "replace",
        "reason": "durable update",
        "content": "# Project Memory",
    }


def test_parse_task_response_preserves_outer_action_with_nested_object() -> None:
    raw = (
        json.dumps(
            {
                "action": "replace",
                "reason": "durable update",
                "content": "# Project Memory",
                "meta": {"action": "none"},
            }
        )
        + "\n\nDone."
    )

    parsed = _parse_task_response(raw)

    assert parsed["action"] == "replace"


def test_parse_task_response_rejects_truncated_outer_with_nested_action() -> None:
    raw = '## Result\n{"action":"replace","meta":{"action":"none"},"content":"# Project Memory'

    with pytest.raises(
        RuntimeError,
        match="did not return valid JSON",
    ):
        _parse_task_response(raw)


def test_parse_task_response_preserves_braces_inside_content() -> None:
    raw = (
        json.dumps(
            {
                "action": "replace",
                "reason": "durable update",
                "content": "# Project Memory\n\nUse {braces} safely.",
            }
        )
        + "\n\nDone."
    )

    parsed = _parse_task_response(raw)

    assert parsed["content"] == "# Project Memory\n\nUse {braces} safely."


def test_parse_task_response_rejects_truncated_json() -> None:
    raw = '## Result\n{"action":"replace","content":"# Project Memory'

    with pytest.raises(
        RuntimeError,
        match="did not return valid JSON",
    ):
        _parse_task_response(raw)


def test_parse_task_response_rejects_invalid_action() -> None:
    raw = '{"action":"append","reason":"unsupported"}'

    with pytest.raises(
        RuntimeError,
        match="action must be 'none' or 'replace'",
    ):
        _parse_task_response(raw)


def test_parse_task_response_rejects_nested_action_inside_non_dict() -> None:
    raw = '[{"action":"none"}] trailing prose'

    with pytest.raises(
        RuntimeError,
        match="did not return valid JSON",
    ):
        _parse_task_response(raw)


def test_parse_task_response_rejects_truncated_non_dict_with_nested_action() -> None:
    raw = '[{"action":"none"}'

    with pytest.raises(
        RuntimeError,
        match="did not return valid JSON",
    ):
        _parse_task_response(raw)


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


def test_maintenance_failure_records_state(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-05-27.md").write_text("### 10:00\n- User discussed maintenance runner.\n", encoding="utf-8")

    cfg = MemSearchConfig()
    cfg.plugins.codex.project_review.enabled = True
    cfg.plugins.codex.project_review.provider = "openai"

    calls = 0

    def runner(ctx, prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider timeout")
        return json.dumps({"action": "none", "reason": "retry succeeded"})

    with pytest.raises(RuntimeError, match="provider timeout"):
        run_due_tasks(platform="codex", project_dir=project, cfg=cfg, llm_runner=runner)

    state = json.loads((project / ".memsearch" / ".maintenance-state.json").read_text(encoding="utf-8"))
    task_state = state["codex.project_review"]
    assert task_state["last_action"] == "error"
    assert task_state["last_failed_at"]
    assert task_state["failed_input_digest"].startswith("sha256:")
    assert "provider timeout" in task_state["last_error"]

    retry = run_due_tasks(platform="codex", project_dir=project, cfg=cfg, llm_runner=runner)
    assert retry[0].action == "none"
    assert calls == 2


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


def test_run_memory_command_allows_transcript_outside_roots(tmp_path: Path) -> None:
    # `memsearch transcript` is a bounded read-only formatter, so it may target a
    # transcript outside the memory roots (originals live in ~/.<agent>/...).
    project = tmp_path / "repo"
    (project / ".memsearch" / "memory").mkdir(parents=True)
    ctx = TaskContext(
        platform="claude-code",
        task="memory_to_skill",
        task_config=PluginMaintenanceTaskConfig(),
        project_dir=project,
        memsearch_dir=project / ".memsearch",
        input_dir=project / ".memsearch" / "memory",
        output_file=project / ".memsearch" / "skill-candidates",
        input_digest="sha256:test",
    )
    out = run_memory_command(f"memsearch transcript {tmp_path}/outside.jsonl", ctx)
    assert "outside allowed memory roots" not in out  # not rejected by the path sandbox

    # A non-transcript command pointed outside the roots is still rejected.
    rejected = run_memory_command(f"grep foo {tmp_path}/outside.txt", ctx)
    assert "outside allowed memory roots" in rejected


def test_run_memory_command_decodes_only_memsearch_as_utf8(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub_script = stub_dir / "memsearch_stub.py"
    stub_script.write_text(
        """\
#!/usr/bin/env python3
import os
import sys

sys.stdout.buffer.write("展开结果丁: 中文内容\\n".encode("utf-8"))
sys.stderr.buffer.write("诊断丁: UTF-8 stderr\\n".encode("utf-8"))
raise SystemExit(int(os.environ.get("MEMSEARCH_STUB_EXIT", "0")))
""",
        encoding="utf-8",
    )
    if os.name == "nt":
        # Windows cannot exec a shebang script; a .cmd shim is what npm/uv installs look like.
        stub = stub_dir / "memsearch.cmd"
        stub.write_text(f'@"{sys.executable}" "{stub_script}" %*\r\n', encoding="utf-8")
    else:
        stub = stub_dir / "memsearch"
        stub.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub_script}" "$@"\n', encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{os.environ['PATH']}")
    ctx = TaskContext(
        platform="codex",
        task="project_review",
        task_config=PluginMaintenanceTaskConfig(),
        project_dir=project,
        memsearch_dir=project / ".memsearch",
        input_dir=memory,
        output_file=project / "PROJECT.md",
        input_digest="sha256:test",
    )

    # The hazard: a cp1252 locale cannot decode memsearch's UTF-8 output. Decode the raw
    # bytes explicitly -- on Windows, subprocess decodes in reader threads, where the
    # error is swallowed and stdout silently becomes None instead of raising.
    raw = subprocess.run(
        [sys.executable, str(stub_script), "expand", "deadbeef"],
        capture_output=True,
        check=False,
    )
    with pytest.raises(UnicodeDecodeError):
        raw.stdout.decode("cp1252", errors="strict")

    real_run = subprocess.run
    completed = []

    def cp1252_default(*args, **kwargs):
        if kwargs.get("text") and "encoding" not in kwargs:
            kwargs["encoding"] = "cp1252"
            kwargs["errors"] = "strict"
        result = real_run(*args, **kwargs)
        completed.append(result)
        return result

    monkeypatch.setattr(maintenance.subprocess, "run", cp1252_default)

    assert run_memory_command("memsearch expand deadbeef", ctx) == "展开结果丁: 中文内容"
    assert completed[-1].stderr == "诊断丁: UTF-8 stderr\n"
    assert completed[-1].returncode == 0

    monkeypatch.setenv("MEMSEARCH_STUB_EXIT", "7")
    assert run_memory_command("memsearch transcript outside.jsonl", ctx) == "展开结果丁: 中文内容"
    assert completed[-1].stderr == "诊断丁: UTF-8 stderr\n"
    assert completed[-1].returncode == 7


def test_run_memory_command_preserves_error_fallback_and_local_command_encoding(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
        output_file=project / "PROJECT.md",
        input_digest="sha256:test",
    )
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if Path(argv[0]).stem.lower() == "memsearch":  # argv[0] may be resolved to memsearch.exe
            raise OSError("command failed")
        return subprocess.CompletedProcess(argv, 0, stdout="local output\n", stderr="")

    monkeypatch.setattr(maintenance.subprocess, "run", fake_run)

    assert run_memory_command("memsearch expand deadbeef", ctx) == "Error: command failed"
    assert calls[-1][1]["encoding"] == "utf-8"
    assert calls[-1][1]["errors"] == "strict"

    subprocess_calls_after_memsearch = len(calls)
    if maintenance._ON_WINDOWS:
        # Windows routes find through the built-in subset (no subprocess), so
        # there is no encoding/argv passthrough to assert here; the empty
        # memory dir yields no matches and no extra subprocess call.
        assert run_memory_command(f"find {memory} -type f -name '*.md'", ctx) == ""
        assert len(calls) == subprocess_calls_after_memsearch
    else:
        assert run_memory_command(f"find {memory} -type f -name '*.md'", ctx) == "local output"
        assert "encoding" not in calls[-1][1]
        assert "errors" not in calls[-1][1]


def _search_ctx(tmp_path: Path) -> tuple[TaskContext, Path]:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-06-01.md").write_text(
        "### 09:00\n- alpha entry about the redis cache\n- beta entry about kubernetes\n",
        encoding="utf-8",
    )
    (memory / "notes").mkdir()
    (memory / "notes" / "deep.md").write_text("### 10:00\n- gamma entry about redis eviction\n", encoding="utf-8")
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
    return ctx, memory


def test_windows_memory_search_finds_files_by_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)

    out = run_memory_command(f"find {memory} -type f -name '*.md'", ctx)

    assert out.count(".md") >= 2
    assert "2026-06-01.md" in out and "deep.md" in out


def test_windows_memory_search_maxdepth_stops_descending(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)

    out = run_memory_command(f"find {memory} -type f -maxdepth 1 -name '*.md'", ctx)

    assert "2026-06-01.md" in out
    assert "deep.md" not in out


def test_windows_memory_search_grep_literal_with_line_numbers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)

    out = run_memory_command(f"grep -n redis {memory / '2026-06-01.md'}", ctx)

    assert "2:- alpha entry about the redis cache" in out
    assert "kubernetes" not in out


def test_windows_memory_search_rejects_regex_pattern(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)

    out = run_memory_command(f"grep 'redis.*cache' {memory / '2026-06-01.md'}", ctx)

    assert out.startswith("Error:")
    assert "literal" in out


def test_windows_memory_search_rejects_paths_outside_roots(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, _memory = _search_ctx(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret redis\n", encoding="utf-8")

    out = run_memory_command(f"grep redis {outside}", ctx)

    assert "outside allowed memory roots" in out


def test_windows_memory_search_rejects_colon_operands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)

    out = run_memory_command(f"grep redis {memory / 'we:ird.md'}", ctx)

    assert "alternate data streams" in out


def test_windows_memory_search_never_traverses_symlinks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret redis\n", encoding="utf-8")
    link = memory / "link"
    try:
        link.symlink_to(outside, target_is_directory=False)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    out = run_memory_command(f"grep redis {link}", ctx)

    assert "secret" not in out
    assert out.startswith("Error:")


def test_windows_memory_search_output_is_capped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)
    big = memory / "big.md"
    big.write_text("redis line\n" * 3000, encoding="utf-8")

    out = run_memory_command(f"grep redis {big}", ctx)

    assert len(out) <= maintenance.MAX_COMMAND_OUTPUT


def test_windows_memory_search_reports_truncation_explicitly(tmp_path: Path, monkeypatch) -> None:
    """A capped output must say so, not look like a complete result."""
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)
    big = memory / "big.md"
    big.write_text("redis line\n" * 3000, encoding="utf-8")

    out = run_memory_command(f"grep redis {big}", ctx)

    assert "truncated" in out
    assert "incomplete" in out
    assert len(out) <= maintenance.MAX_COMMAND_OUTPUT
    # Some real matches still precede the marker, so the caller gets both.
    assert out.startswith("redis line")


def test_windows_memory_search_truncation_marker_fits_cap(tmp_path: Path, monkeypatch) -> None:
    """The truncation notice must survive even when the last line is huge."""
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)
    huge = memory / "huge.md"
    huge.write_text("redis " + "x" * (maintenance.MAX_COMMAND_OUTPUT * 2) + "\nredis tail\n", encoding="utf-8")

    out = run_memory_command(f"grep redis {huge}", ctx)

    assert len(out) <= maintenance.MAX_COMMAND_OUTPUT
    assert out.endswith("results are incomplete")


def test_windows_memory_search_no_truncation_marker_on_complete_results(tmp_path: Path, monkeypatch) -> None:
    """Complete results must not claim truncation."""
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)

    out = run_memory_command(f"grep -rn redis {memory}", ctx)

    assert "truncated" not in out
    assert "2026-06-01.md" in out and "deep.md" in out


@pytest.mark.skipif(os.name != "nt", reason="Windows-native path semantics")
def test_windows_memory_search_rejects_junction_on_windows(tmp_path: Path) -> None:
    """A directory junction must not be traversed (real reparse point, not a symlink)."""
    ctx, memory = _search_ctx(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret redis\n", encoding="utf-8")
    # mklink /J requires cmd.exe; Python has no junction API.
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(memory / "junction"), str(outside)], check=True, capture_output=True
    )

    out = run_memory_command(f"grep -r redis {memory}", ctx)

    assert "secret" not in out


@pytest.mark.skipif(os.name != "nt", reason="Windows-native path semantics")
def test_windows_memory_search_accepts_native_windows_paths(tmp_path: Path) -> None:
    """Backslash separators and drive-letter absolutes must work end to end."""
    ctx, memory = _search_ctx(tmp_path)

    native = str(memory / "2026-06-01.md")
    out = run_memory_command(f"grep -n redis {native}", ctx)

    assert "2:- alpha entry about the redis cache" in out


@pytest.mark.skipif(os.name != "nt", reason="Windows-native path semantics")
def test_windows_memory_search_rejects_unc_paths(tmp_path: Path) -> None:
    """UNC device operands are refused before any filesystem access."""
    ctx, _memory = _search_ctx(tmp_path)

    out = run_memory_command("grep redis \\\\?\\C:\\nonexistent\\dir", ctx)

    assert out.startswith("Error:")
    assert "outside allowed memory roots" in out


def test_run_memory_command_routes_find_and_grep_through_subset_on_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "_ON_WINDOWS", True)
    ctx, memory = _search_ctx(tmp_path)

    out = run_memory_command(f"grep -rn redis {memory}", ctx)

    assert "2026-06-01.md" in out and "deep.md" in out
    assert "redis" in out
