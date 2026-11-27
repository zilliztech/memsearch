from __future__ import annotations

import importlib
import json
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/antigravity/scripts"))
    return importlib.import_module("agy_maintenance")


def context(tmp_path):
    return SimpleNamespace(
        task="memory_to_skill",
        task_config=SimpleNamespace(model="native-test"),
        project_dir=tmp_path,
        memsearch_dir=tmp_path / ".memsearch",
        input_dir=tmp_path / ".memsearch/memory",
        input_digest="synthetic-digest",
    )


def test_adaptive_reads_receive_prior_results_without_prefetch(adapter, tmp_path, monkeypatch):
    ctx = context(tmp_path)
    first, second = tmp_path / "first transcript.jsonl", tmp_path / "second.jsonl"
    prompt = f"<!-- session:first turn:0 transcript:{str(first).replace(' ', '%20')} -->\n<!-- session:second turn:7 transcript:{second} -->"
    calls, prompts = [], []

    def execute(argv, _cwd):
        calls.append(argv)
        return "inspect succeeded; next confirm second session" if len(calls) == 1 else "verify --strict succeeded"

    monkeypatch.setattr(adapter, "_executor", lambda _anchors: execute)

    def generate(text, *, model):
        assert model == "native-test"
        prompts.append(text)
        if len(prompts) == 1:
            assert "inspect succeeded" not in text
            return json.dumps({"memory_command": f"memsearch transcript {shlex.quote(str(first))} --turn 0"})
        if len(prompts) == 2:
            assert "inspect succeeded" in text
            return json.dumps({"memory_command": f"memsearch transcript {second} --turn 7"})
        assert "verify --strict succeeded" in text
        return '{"skills":[]}'

    monkeypatch.setattr(adapter.agy_native, "generate", generate)
    assert json.loads(adapter.generate_task(ctx, prompt)) == {"skills": []}
    assert len(calls) == 2 and calls[0][2] == str(first)
    audit = json.loads((ctx.memsearch_dir / ".antigravity/native-maintenance/memory_to_skill.json").read_text())
    assert audit["completed"] and len(audit["reads"]) == 2
    assert "inspect succeeded" not in json.dumps(audit)


def test_native_bridge_rejects_foreign_paths_options_and_writes(adapter, tmp_path, monkeypatch):
    from memsearch.maintenance import run_memory_command

    path = tmp_path / "transcript with spaces.jsonl"
    execute = adapter._executor({(str(path), "4")})
    invoked = []
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda argv, **kw: invoked.append(argv) or SimpleNamespace(returncode=0, stdout="public turns"),
    )
    ctx = context(tmp_path)
    for command in [
        "memsearch index .",
        "cat secret",
        "memsearch expand deadbeef --milvus-uri http://foreign",
        f"memsearch transcript {tmp_path / 'foreign.jsonl'} --turn 4",
        f"memsearch transcript {shlex.quote(str(path))} --turn 8",
        f"memsearch transcript {shlex.quote(str(path))} --turn 4 --context 100",
        f"memsearch transcript {shlex.quote(str(path))} --turn 4; touch bad",
    ]:
        assert run_memory_command(command, ctx, executor=execute).startswith("Error:")
    assert not invoked
    assert (
        run_memory_command(f"memsearch transcript {shlex.quote(str(path))} --turn 4 --context 3", ctx, executor=execute)
        == "public turns"
    )
    assert invoked[0][-5:] == [str(path), "--turn", "4", "--context", "3"]
    assert "--project-dir" in invoked[0]


def test_native_read_budget_is_bounded_even_for_invalid_requests(adapter, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        adapter.agy_native, "generate", lambda text, **kw: calls.append(text) or '{"memory_command":"cat secret"}'
    )
    with pytest.raises(adapter.NativeGenerationError, match="budget"):
        adapter.generate_task(context(tmp_path), "synthetic input")
    assert len(calls) == 4
    assert "no more reads" in calls[-1]


def test_shared_bridge_validates_before_host_executor(tmp_path):
    from memsearch.maintenance import run_memory_command

    calls = []
    assert run_memory_command(
        "curl https://example.test", context(tmp_path), executor=lambda *args: calls.append(args)
    ).startswith("Error:")
    assert not calls
