"""Regression coverage for model Markdown responses and native Windows commands."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from memsearch import maintenance, skills
from memsearch.config import MemSearchConfig, PluginMaintenanceTaskConfig


@pytest.fixture
def context(tmp_path):
    project = tmp_path / "project"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "notes.md").write_text("- Run the tests before the release.\n", encoding="utf-8")
    return maintenance.TaskContext(
        platform="dsh",
        task="project_review",
        task_config=PluginMaintenanceTaskConfig(),
        project_dir=project,
        memsearch_dir=project / ".memsearch",
        input_dir=memory,
        output_file=project / ".memsearch" / "PROJECT.md",
        input_digest="test",
    )


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "Reasoning first.\n{}\nDone."])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_task_response_preserves_literal_markdown_newlines(wrapper, newline):
    content = f"# Project Memory{newline}{newline}- 发布前运行测试。"
    raw = '{"action":"replace","content":"' + content + '"}'
    assert maintenance._parse_task_response(wrapper.format(raw))["content"] == content


@pytest.mark.parametrize("task,filename", [("project_review", "PROJECT.md"), ("user_profile", "USER.md")])
def test_multiline_maintenance_result_reaches_output(context, task, filename):
    cfg = MemSearchConfig()
    setting = getattr(cfg.plugins.dsh, task)
    setting.enabled = True
    output = context.memsearch_dir / filename
    setting.output_file = str(output)
    content = "# Memory\n\n- Run the tests before release."
    raw = '{"action":"replace","content":"' + content + '"}'

    results = maintenance.run_due_tasks(
        platform="dsh", project_dir=context.project_dir, cfg=cfg, force=True, llm_runner=lambda *_: raw
    )

    assert next(result for result in results if result.task == task).action == "replace"
    assert output.read_text(encoding="utf-8") == content + "\n"


@pytest.mark.parametrize(
    "raw",
    ['{"action":"replace","content":"# Truncated\n', '{"action":"delete","content":"bad\noperation"}'],
)
def test_invalid_maintenance_result_preserves_existing_file(context, raw):
    cfg = MemSearchConfig()
    cfg.plugins.dsh.project_review.enabled = True
    cfg.plugins.dsh.project_review.output_file = str(context.output_file)
    context.output_file.write_text("# Keep existing memory\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        maintenance.run_due_tasks(
            platform="dsh", project_dir=context.project_dir, cfg=cfg, force=True, llm_runner=lambda *_: raw
        )
    assert context.output_file.read_text(encoding="utf-8") == "# Keep existing memory\n"
    state = json.loads((context.memsearch_dir / ".maintenance-state.json").read_text())
    assert state["dsh.project_review"]["last_error"]
    assert "last_success_at" not in state["dsh.project_review"]


def test_distill_literal_newlines_create_review_candidate(context):
    cfg = MemSearchConfig()
    cfg.plugins.dsh.memory_to_skill.enabled = True
    body = "## Run tests\n\n1. Run pytest.\n2. Report failures."
    raw = '{"skills":[{"name":"run-tests","description":"Run the test suite.","occurrences":3,"body":"' + body + '"}]}'
    result = skills.distill(platform="dsh", project_dir=context.project_dir, cfg=cfg, llm_runner=lambda *_: raw)
    assert result.created == ["run-tests"]
    candidate = context.memsearch_dir / "skill-candidates" / "run-tests"
    assert body in (candidate / "SKILL.md").read_text(encoding="utf-8")
    assert json.loads((candidate / "meta.json").read_text())["status"] == "candidate"


@pytest.mark.parametrize("raw", ['{"skills":[{"body":"unfinished\n', '{"skills":"wrong\nshape"}'])
def test_distill_still_rejects_invalid_results(raw):
    with pytest.raises(RuntimeError):
        skills._parse_distill_response(raw)


@pytest.mark.parametrize(
    "argument,expected",
    [
        (r"C:\Users\Lin\logs\session.jsonl", [r"C:\Users\Lin\logs\session.jsonl"]),
        (r'"C:\Users\Lin Wang\logs\session.jsonl"', [r"C:\Users\Lin Wang\logs\session.jsonl"]),
        (r"'C:\My Logs\session.jsonl'", [r"C:\My Logs\session.jsonl"]),
        (r"\\server\share\session.jsonl", [r"\\server\share\session.jsonl"]),
        ('"C:\\My Logs\\"', ["C:\\My Logs\\"]),
        (r'--turn="turn-1" "C:\My Logs\session.jsonl"', ["--turn=turn-1", r"C:\My Logs\session.jsonl"]),
    ],
)
def test_memory_command_preserves_windows_arguments(context, monkeypatch, argument, expected):
    monkeypatch.setattr(maintenance, "os", SimpleNamespace(name="nt"))
    captured = []
    monkeypatch.setattr(maintenance, "_run_restricted", lambda argv, cwd: captured.append(argv) or "ok")
    assert maintenance.run_memory_command(f"memsearch transcript {argument}", context) == "ok"
    assert captured == [["memsearch", "transcript", *expected]]


def test_memory_command_preserves_posix_escaping(context, monkeypatch):
    monkeypatch.setattr(maintenance, "os", SimpleNamespace(name="posix"))
    captured = []
    monkeypatch.setattr(maintenance, "_run_restricted", lambda argv, cwd: captured.append(argv) or "ok")
    assert maintenance.run_memory_command(r"memsearch transcript /tmp/My\ Logs/session.jsonl", context) == "ok"
    assert captured[0][2] == "/tmp/My Logs/session.jsonl"


@pytest.mark.parametrize("system,extension", [("nt", ".cmd"), ("nt", ".bat"), ("nt", ".exe"), ("posix", "")])
@pytest.mark.parametrize("argument", ["%USERPROFILE%", "!PROFILE!", "note^name"])
def test_batch_expansion_guard_is_limited_to_windows_launchers(context, monkeypatch, system, extension, argument):
    monkeypatch.setattr(maintenance, "os", SimpleNamespace(name=system, environ=os.environ))
    monkeypatch.setattr(shutil, "which", lambda _: "memsearch" + extension)
    calls = []

    def record(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(maintenance.subprocess, "run", record)
    result = maintenance.run_memory_command(f"memsearch transcript {argument}", context)
    if system == "nt" and extension in {".cmd", ".bat"}:
        assert "Windows batch commands" in result
        assert calls == []
    else:
        assert result == "ok"
        assert calls[0][-1] == argument


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows path resolution")
def test_windows_paths_obey_memory_roots(context, tmp_path):
    inside = context.input_dir / "notes.md"
    outside = tmp_path / "outside.txt"
    roots = [context.project_dir]
    validate = maintenance._validate_paths_in_args
    assert validate([str(inside)], roots, cwd=context.project_dir, allow_hash=False) == ""
    other_drive = "C:" if context.project_dir.drive.upper() != "C:" else "D:"
    for path in [str(outside), f"{other_drive}outside.txt"]:
        assert "outside allowed memory roots" in validate([path], roots, cwd=context.project_dir, allow_hash=False)


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows batch launcher")
def test_windows_maintenance_reads_real_transcript_through_cmd(context, tmp_path, monkeypatch):
    source = tmp_path / "original sessions" / "conversation.jsonl"
    source.parent.mkdir()
    source.write_text(
        json.dumps({"type": "user", "uuid": "turn-861", "message": {"content": "测试标记: cedar-861"}}) + "\n",
        encoding="utf-8",
    )
    executable = tmp_path / "bin"
    executable.mkdir()
    entrypoint = executable / "entry.py"
    entrypoint.write_text("from memsearch.cli import cli\ncli()\n", encoding="utf-8")
    (executable / "memsearch.cmd").write_text(f'@"{sys.executable}" "{entrypoint}" %*\r\n', encoding="utf-8")
    monkeypatch.setenv("PATH", str(executable) + os.pathsep + os.environ["PATH"])

    result = maintenance.run_memory_command(f'memsearch transcript "{source}" --json-output', context)

    turns = json.loads(result)
    assert turns[0]["uuid"] == "turn-861"
    assert "cedar-861" in turns[0]["text"]
