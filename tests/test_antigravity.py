from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/antigravity"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "scripts"))
    spec = importlib.util.spec_from_file_location("agy_runtime", PLUGIN / "scripts/runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("MEMSEARCH_DIR", raising=False)
    for key in ("MEMSEARCH_DISABLE", "MEMSEARCH_AGY_HELPER", "MEMSEARCH_AGY_WORKER"):
        monkeypatch.delenv(key, raising=False)
    from memsearch import config

    monkeypatch.setattr(config, "GLOBAL_CONFIG_PATH", tmp_path / "global.toml")
    monkeypatch.chdir(tmp_path)
    return module


def payload(tmp_path, *, turn=0, session="synthetic-session"):
    transcript = tmp_path / "transcript.jsonl"
    entries = [
        {
            "step_index": turn,
            "type": "USER_INPUT",
            "source": "USER_EXPLICIT",
            "content": "Remember quartz-47, port 4182",
        },
        {"step_index": turn + 1, "type": "PLANNER_RESPONSE", "content": "Recorded quartz-47 and port 4182"},
    ]
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return {
        "workspacePaths": [str(tmp_path)],
        "conversationId": session,
        "transcriptPath": str(transcript),
        "fullyIdle": True,
        "executionNum": 1,
    }


def test_hook_uses_workspace_not_plugin_cwd_and_injects_once(runtime, tmp_path, monkeypatch):
    data = payload(tmp_path)
    monkeypatch.chdir(PLUGIN)
    result = runtime.hook("session-start", data)
    text = result["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert str(tmp_path) in text
    assert "search → expand → transcript" in text
    assert runtime.hook("pre-invocation", data) == {}
    assert (tmp_path / ".memsearch/.antigravity/hints").is_dir()


def test_missing_workspace_never_falls_back_to_cwd(runtime):
    with pytest.raises(ValueError, match="workspacePaths"):
        runtime.roots({})


def test_explicit_memory_and_collection_scope(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv("MEMSEARCH_DIR", "custom-memory")
    project, memory = runtime.roots(payload(tmp_path))
    assert memory == tmp_path / "custom-memory"
    derived = runtime.collection(project, memory)
    assert derived.startswith("ms_custom_memory_")
    cfg = runtime.config(project, memory, derived)
    assert cfg.embedding.provider == "onnx"
    assert cfg.milvus.collection == derived
    assert cfg.plugins.antigravity.project_review.output_file == str(memory / "PROJECT.md")
    assert cfg.plugins.antigravity.user_profile.output_file == str(memory / "USER.md")


def test_explicit_embedding_remote_uri_and_collection_survive(runtime, tmp_path):
    from memsearch import config

    config.save_config(
        {
            "embedding": {"provider": "ollama", "model": "test-model"},
            "milvus": {"uri": "http://127.0.0.1:19530", "collection": "explicit"},
        },
        tmp_path / "global.toml",
    )
    cfg = runtime.config(tmp_path, tmp_path / ".memsearch", "derived")
    assert cfg.embedding.provider == "ollama"
    assert cfg.embedding.model == "test-model"
    assert cfg.milvus.uri == "http://127.0.0.1:19530"
    assert cfg.milvus.collection == "explicit"


def test_stop_snapshots_before_detach_and_repeated_stop_is_idempotent(runtime, tmp_path, monkeypatch):
    data = payload(tmp_path)
    memory = tmp_path / ".memsearch"
    monkeypatch.setattr(runtime, "detach", lambda *_: payload(tmp_path, turn=3))
    runtime.hook("stop", data)
    job = next((memory / ".antigravity/jobs").glob("*.json"))
    captured = json.loads(job.read_text())
    assert captured["turn"] == "0"
    assert captured["entries"][0]["step_index"] == 0
    data = payload(tmp_path)
    data["executionNum"] = 8
    runtime.hook("stop", data)
    assert len(list(job.parent.glob("*.json"))) == 1


@pytest.mark.parametrize("flag", ["MEMSEARCH_DISABLE", "MEMSEARCH_AGY_HELPER", "MEMSEARCH_AGY_WORKER"])
def test_recursion_guards(runtime, tmp_path, monkeypatch, flag):
    monkeypatch.setenv(flag, "1")
    assert runtime.hook("stop", payload(tmp_path)) == {}
    assert not (tmp_path / ".memsearch").exists()


def test_non_idle_or_incomplete_turn_does_not_queue(runtime, tmp_path):
    data = payload(tmp_path)
    data["fullyIdle"] = False
    assert runtime.snapshot(data, tmp_path, tmp_path / ".memsearch") is None
    data["fullyIdle"] = True
    Path(data["transcriptPath"]).write_text('{"type":"USER_INPUT","step_index":0}\n')
    assert runtime.snapshot(data, tmp_path, tmp_path / ".memsearch") is None


def test_detached_streams_and_new_session(runtime, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    runtime.detach(tmp_path, tmp_path / ".memsearch")
    kw = calls[0][1]
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
    assert kw["start_new_session"] and kw["close_fds"]
    assert kw["cwd"] == tmp_path


def test_index_failure_retries_without_resummarizing_or_duplicate_journal(runtime, tmp_path, monkeypatch):
    memory = tmp_path / ".memsearch"
    job_path = runtime.snapshot(payload(tmp_path), tmp_path, memory)
    calls = []
    monkeypatch.setattr(runtime, "summarize", lambda *_: calls.append("summary") or "- quartz-47 uses port 4182")
    monkeypatch.setattr(runtime, "maintenance", lambda *_: None)

    def failed_index(*_):
        calls.append("failed_index")
        raise RuntimeError("connection down")

    monkeypatch.setattr(runtime, "run_index", failed_index)
    runtime.worker(tmp_path, memory)
    first = next((memory / "memory").glob("*.md")).read_text()
    assert "quartz-47 uses port 4182" in first
    assert json.loads(job_path.read_text())["stage"] == "written"
    monkeypatch.setattr(runtime, "run_index", lambda *_: calls.append("index"))
    runtime.worker(tmp_path, memory)
    runtime.worker(tmp_path, memory)
    assert next((memory / "memory").glob("*.md")).read_text() == first
    assert calls == ["summary", "failed_index", "index"]
    assert json.loads(job_path.read_text())["stage"] == "done"


def test_failed_summary_keeps_retryable_snapshot_without_raw_fallback(runtime, tmp_path, monkeypatch):
    memory = tmp_path / ".memsearch"
    path = runtime.snapshot(payload(tmp_path), tmp_path, memory)

    def fail(*_):
        raise RuntimeError("sensitive provider detail")

    monkeypatch.setattr(runtime, "summarize", fail)
    monkeypatch.setattr(runtime, "maintenance", lambda *_: None)
    runtime.worker(tmp_path, memory)
    state = json.loads(path.read_text())
    assert state["stage"] == "captured" and state["entries"]
    assert state["last_error"] == "RuntimeError"
    assert "sensitive provider detail" not in path.read_text()
    assert not (memory / "memory").exists()


def test_concurrent_append_and_crash_replay(runtime, tmp_path):
    memory = tmp_path / ".memsearch"
    first = json.loads(runtime.snapshot(payload(tmp_path), tmp_path, memory).read_text())
    jobs = [{**first, "id": str(i), "summary": f"- fact-{i}"} for i in range(12)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda job: runtime.append_summary(job, memory), jobs * 2))
    text = next((memory / "memory").glob("*.md")).read_text()
    for i in range(12):
        assert text.count(f"- fact-{i}\n") == 1


def test_antigravity_config_roundtrip(runtime, tmp_path):
    from memsearch.config import config_to_dict, resolve_config, save_config

    value = {
        "plugins": {
            "antigravity": {
                "summarize": {"provider": "test", "model": "test-small"},
                "memory_to_skill": {"enabled": True, "min_occurrences": 2},
            }
        }
    }
    save_config(value, tmp_path / "global.toml")
    cfg = resolve_config()
    assert cfg.plugins.antigravity.summarize.provider == "test"
    assert config_to_dict(cfg)["plugins"]["antigravity"]["memory_to_skill"]["min_occurrences"] == 2


def test_worker_closes_index_client_even_on_failure(runtime, tmp_path, monkeypatch):
    import memsearch

    closed = []

    class FailedClient:
        def __init__(self, *args, **kwargs):
            pass

        async def index_with_report(self):
            raise OSError("synthetic index failure")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(memsearch, "MemSearch", FailedClient)
    memory = tmp_path / ".memsearch"
    with pytest.raises(OSError):
        runtime.run_index(memory, runtime.config(tmp_path, memory, "test"))
    assert closed == [True]
    assert json.loads((memory / ".index-state.json").read_text())["status"] == "error"


def test_native_response_validation_and_isolation(runtime, tmp_path, monkeypatch):
    import agy_native

    calls = []

    class FakeProcess:
        returncode = 0

        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            agents = list(Path(kwargs["cwd"]).glob(".agents/plugins/*/agents/*.md"))
            text = agents[0].read_text()
            assert "inheritMcp: false" in text and "inheritCustomizations: false" in text
            assert "tools: []" in text

        def communicate(self, **kwargs):
            return json.dumps({"status": "SUCCESS", "response": "- synthetic"}), "never summary"

    monkeypatch.setattr(agy_native.subprocess, "Popen", FakeProcess)
    assert agy_native.generate("test") == "- synthetic"
    command, kwargs = calls[0]
    assert command[command.index("--model") + 1] == "gemini-4-hydrogen-low"
    assert "--dangerously-skip-permissions" not in command
    assert kwargs["env"]["MEMSEARCH_AGY_HELPER"] == "1"
    assert kwargs["stdin"] == subprocess.DEVNULL
    monkeypatch.setattr(FakeProcess, "communicate", lambda *_a, **_kw: ('{"status":"ERROR","response":"fake"}', ""))
    with pytest.raises(RuntimeError, match="SUCCESS"):
        agy_native.generate("test")
    monkeypatch.setattr(FakeProcess, "communicate", lambda *_a, **_kw: ("", "- diagnostic"))
    with pytest.raises(RuntimeError, match="invalid JSON"):
        agy_native.generate("test")


def test_lightweight_hook_does_not_import_installed_core(tmp_path):
    poison = tmp_path / "memsearch"
    poison.mkdir()
    (poison / "__init__.py").write_text('raise RuntimeError("hooks must not import core")')
    data = payload(tmp_path)
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(PLUGIN / "scripts/runtime.py"), "session-start"],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        cwd=PLUGIN,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "MEMSEARCH_DIR": str(tmp_path / "memory")},
        timeout=3,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["injectSteps"]
    assert time.monotonic() - start < 3


def test_source_bootstrap_selects_current_checkout(runtime, monkeypatch):
    import bootstrap

    monkeypatch.setattr(bootstrap.os, "execve", lambda *_: None)
    bootstrap.bootstrap(PLUGIN / "scripts/runtime.py")
    assert sys.path[0] == str(ROOT / "src")


def test_prompt_copies_match_shared():
    for source in (ROOT / "plugins/_shared/prompts").glob("*.txt"):
        assert (PLUGIN / "prompts" / source.name).read_bytes() == source.read_bytes()


def test_named_provider_summary_uses_shared_sdk_with_mock_transport(runtime, tmp_path, monkeypatch):
    import httpx
    import openai

    from memsearch.config import LLMProviderConfig

    memory = tmp_path / ".memsearch"
    cfg = runtime.config(tmp_path, memory, "test")
    cfg.plugins.antigravity.summarize.provider = "local-mock"
    cfg.plugins.antigravity.summarize.model = "task-model"
    cfg.llm.providers["local-mock"] = LLMProviderConfig(
        type="openai", model="provider-model", base_url="http://127.0.0.1:1/v1", api_key="placeholder"
    )
    observed = []

    def handle(request):
        body = json.loads(request.content)
        observed.append(body)
        text = body["messages"][0]["content"]
        assert request.headers["Authorization"] == "Bearer placeholder"
        assert "quartz-47" in text and "4182" in text
        summary = "- " + text.split("[Assistant]: ")[-1]
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "task-model",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": summary}}
                ],
            },
        )

    real_client = openai.AsyncOpenAI

    def mock_client(**kwargs):
        return real_client(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))

    monkeypatch.setattr(openai, "AsyncOpenAI", mock_client)
    job = json.loads(runtime.snapshot(payload(tmp_path), tmp_path, memory).read_text())
    summary = runtime.summarize(job, cfg)
    assert summary == "- Recorded quartz-47 and port 4182"
    assert observed[0]["model"] == "task-model"


def test_all_three_maintenance_tasks_opt_in_interval_and_memory_root(runtime, tmp_path, monkeypatch):
    from memsearch import skills

    memory = tmp_path / "custom-memory"
    (memory / "memory").mkdir(parents=True)
    (memory / "memory/2026-11-27.md").write_text("- synthetic reusable workflow\n")
    cfg = runtime.config(tmp_path, memory, "test")
    calls = []

    def native(prompt, *, model=""):
        calls.append((prompt, model))
        if "candidate" in prompt.lower():
            return '{"skills":[]}'
        return '{"action":"replace","content":"# Synthetic memory\\n- retained","reason":"test"}'

    import agy_native

    monkeypatch.setattr(agy_native, "generate", native)
    # Candidate-store commits are separately tested in core; this phase does
    # not create commits even inside the synthetic candidate repository.
    monkeypatch.setattr(skills, "_ensure_git", lambda root: root.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(skills, "_git_commit", lambda *_: None)
    results, skill = runtime.maintenance(tmp_path, memory, cfg)
    assert all(r.action == "disabled" for r in results) and skill.action == "disabled"
    assert not calls
    for task in ("project_review", "user_profile", "memory_to_skill"):
        getattr(cfg.plugins.antigravity, task).enabled = True
        getattr(cfg.plugins.antigravity, task).model = "background-model"
    results, skill = runtime.maintenance(tmp_path, memory, cfg)
    assert len(calls) == 3 and all(model == "background-model" for _, model in calls)
    assert all("synthetic reusable workflow" in prompt for prompt, _ in calls)
    assert all(r.action == "replace" for r in results)
    assert skill.action == "none"
    assert (memory / "PROJECT.md").exists() and (memory / "USER.md").exists()
    results, skill = runtime.maintenance(tmp_path, memory, cfg)
    assert all(r.action == "skip" for r in results) and skill.action == "skip"
    assert len(calls) == 3
    state = json.loads((memory / ".maintenance-state.json").read_text())
    assert set(state) == {"antigravity.project_review", "antigravity.user_profile", "antigravity.memory_to_skill"}


def test_snapshot_uses_full_companion_before_next_turn(runtime, tmp_path):
    data = payload(tmp_path)
    compact = Path(data["transcriptPath"])
    full = compact.with_name("transcript_full.jsonl")
    rows = [json.loads(line) for line in compact.read_text().splitlines()]
    rows[-1]["content"] = "full untruncated response"
    full.write_text("\n".join(json.dumps(e) for e in rows))
    path = runtime.snapshot(data, tmp_path, tmp_path / ".memsearch")
    payload(tmp_path, turn=3)
    assert json.loads(path.read_text())["entries"][-1]["content"] == "full untruncated response"


def test_retry_retains_original_scope_after_environment_change(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv("MEMSEARCH_DIR", "original-memory")
    project, memory = runtime.roots(payload(tmp_path))
    path = runtime.snapshot(payload(tmp_path), project, memory)
    original_collection = json.loads(path.read_text())["collection"]
    monkeypatch.delenv("MEMSEARCH_DIR")
    seen = []
    monkeypatch.setattr(runtime, "summarize", lambda *_: "- synthetic")
    monkeypatch.setattr(runtime, "run_index", lambda _memory, cfg: seen.append(cfg.milvus.collection))
    monkeypatch.setattr(runtime, "maintenance", lambda *_: None)
    runtime.worker(project, memory)
    assert seen == [original_collection]


def test_long_native_prompt_streams_input_and_uses_only_final_response(runtime, monkeypatch):
    import agy_native

    prompt = "synthetic 文本 " * 4000

    class Process:
        returncode = 0

        def __init__(self, command, **kwargs):
            assert prompt not in command
            assert command[command.index("--input-format") + 1] == "stream-json"
            request = json.load(kwargs["stdin"])
            assert request == {"event": "user", "message": {"content": prompt}}

        def communicate(self, **kwargs):
            return "\n".join(
                [
                    '{"event":"init","tools":[]}',
                    '{"event":"step_update","text_delta":"partial"}',
                    '{"event":"result","result":{"status":"SUCCESS","response":"- complete"}}',
                ]
            ), "diagnostic"

    monkeypatch.setattr(agy_native.subprocess, "Popen", Process)
    assert agy_native.generate(prompt) == "- complete"


def test_degraded_index_keeps_failed_file_details(runtime, tmp_path, monkeypatch):
    import memsearch
    from memsearch.index_report import IndexFailure, IndexReport

    closed = []

    class PartialClient:
        def __init__(self, *args, **kwargs):
            pass

        async def index_with_report(self):
            return IndexReport(
                indexed_chunks=0,
                total_files=1,
                indexed_files=0,
                failed_files=(IndexFailure(path="failed.md", error="synthetic"),),
            )

        def close(self):
            closed.append(True)

    monkeypatch.setattr(memsearch, "MemSearch", PartialClient)
    memory = tmp_path / ".memsearch"
    with pytest.raises(RuntimeError, match="failed files"):
        runtime.run_index(memory, runtime.config(tmp_path, memory, "test"))
    state = json.loads((memory / ".index-state.json").read_text())
    assert state["status"] == "degraded"
    assert state["failed_files"][0]["path"] == "failed.md"
    assert closed == [True]


def test_reverse_snapshot_reader_skips_old_history(runtime, tmp_path):
    path = tmp_path / "transcript.jsonl"
    old = {"step_index": 0, "type": "USER_INPUT", "content": "old" * 30000}
    recent = [
        {"step_index": 20, "type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "最新问题"},
        {"step_index": 21, "type": "PLANNER_RESPONSE", "content": "最新回答"},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [old, *recent]) + "\n")
    assert runtime.read_entries(path) == recent


def test_real_lite_index_scoped_search_expand_and_fixture_transcript(runtime, tmp_path, monkeypatch, capsys):
    from memsearch import core
    from memsearch.config import save_config

    class Embedding:
        dimension = 4
        model_name = "antigravity-fixture"
        batch_size = 8

        async def embed(self, texts):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(core, "get_provider", lambda *_a, **_kw: Embedding())
    save_config({"milvus": {"uri": str(tmp_path / "private.db")}}, tmp_path / "global.toml")
    memory = tmp_path / ".memsearch"
    data = payload(tmp_path)
    data["transcriptPath"] = str(ROOT / "tests/fixtures/antigravity/transcript.jsonl")
    job = json.loads(runtime.snapshot(data, tmp_path, memory).read_text())
    job["summary"] = "- The sample device quartz-47 uses port 4182."
    runtime.append_summary(job, memory)
    cfg = runtime.config(tmp_path, memory, runtime.collection(tmp_path, memory))
    runtime.run_index(memory, cfg)
    foreign = tmp_path / "other-project"
    foreign.mkdir()
    foreign_memory = foreign / ".memsearch"
    (foreign_memory / "memory").mkdir(parents=True)
    (foreign_memory / "memory/foreign.md").write_text("# Foreign\n- quartz-47 is secret-foreign\n")
    runtime.run_index(
        foreign_memory, runtime.config(foreign, foreign_memory, runtime.collection(foreign, foreign_memory))
    )
    capsys.readouterr()

    def invoke(*arguments):
        with pytest.raises(SystemExit) as exited:
            runtime.scoped_cli(list(arguments), cfg)
        assert exited.value.code == 0
        return json.loads(capsys.readouterr().out)

    hits = invoke("search", "quartz-47", "-j")
    assert hits and all(hit["source"].startswith(str(memory / "memory")) for hit in hits)
    expanded = invoke("expand", hits[0]["chunk_hash"], "-j")
    assert expanded["anchor"]["turn"] == "0"
    turns = invoke("transcript", expanded["anchor"]["transcript"], "--turn", "0", "-j")
    assert turns[1]["tools"][0]["name"] == "read_file"
    assert "4182" in turns[-1]["text"]


def test_multi_workspace_uses_host_cwd_and_most_specific_root(runtime, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    nested = second / "nested"
    first.mkdir()
    nested.mkdir(parents=True)
    assert runtime.roots({"workspacePaths": [str(first), str(second)], "cwd": str(nested)})[0] == second
    assert runtime.roots({"workspacePaths": [str(second), str(nested)], "cwd": str(nested)})[0] == nested
    assert runtime.roots({"workspacePaths": [str(first), str(second)], "cwd": str(tmp_path)})[0] == first


def test_startup_recovers_pending_jobs_without_model_work_in_hook(runtime, tmp_path, monkeypatch):
    data = payload(tmp_path)
    memory = tmp_path / ".memsearch"
    runtime.snapshot(data, tmp_path, memory)
    launched = []
    monkeypatch.setattr(runtime, "detach", lambda project, root: launched.append((project, root)))
    runtime.hook("session-start", data)
    assert launched == [(tmp_path, memory)]


def test_pending_jobs_replay_chronologically(runtime, tmp_path, monkeypatch):
    memory = tmp_path / ".memsearch"
    early = runtime.snapshot(payload(tmp_path, turn=0), tmp_path, memory)
    late = runtime.snapshot(payload(tmp_path, turn=4), tmp_path, memory)
    for path, timestamp in ((early, "2026-11-27T01:00:00Z"), (late, "2026-11-27T01:00:10Z")):
        job = json.loads(path.read_text())
        job["created_at"] = timestamp
        runtime.write_json(path, job)
    called = []
    monkeypatch.setattr(runtime, "summarize", lambda job, _cfg: called.append(job["turn"]) or f"- turn {job['turn']}")
    monkeypatch.setattr(runtime, "run_index", lambda *_: None)
    monkeypatch.setattr(runtime, "maintenance", lambda *_: None)
    runtime.worker(tmp_path, memory)
    assert called == ["0", "4"]
    journal = next((memory / "memory").glob("*.md")).read_text()
    assert journal.startswith("# ") and "## Session " in journal
    assert journal.index("- turn 0") < journal.index("- turn 4")


def test_failed_earlier_summary_preserves_correction_order(runtime, tmp_path, monkeypatch):
    memory = tmp_path / ".memsearch"
    first = runtime.snapshot(payload(tmp_path, turn=0), tmp_path, memory)
    second = runtime.snapshot(payload(tmp_path, turn=4), tmp_path, memory)
    calls = []

    def unavailable(job, _cfg):
        calls.append(job["turn"])
        raise RuntimeError("synthetic unavailable model")

    monkeypatch.setattr(runtime, "summarize", unavailable)
    monkeypatch.setattr(runtime, "run_index", lambda *_: None)
    monkeypatch.setattr(runtime, "maintenance", lambda *_: None)
    runtime.worker(tmp_path, memory)
    assert calls == ["0"]
    assert json.loads(first.read_text())["stage"] == "captured"
    assert "summary_attempts" not in json.loads(second.read_text())
    assert not (memory / "memory").exists()
    monkeypatch.setattr(runtime, "summarize", lambda job, _cfg: f"- turn {job['turn']}")
    runtime.worker(tmp_path, memory)
    journal = next((memory / "memory").glob("*.md")).read_text()
    assert journal.index("- turn 0") < journal.index("- turn 4")


@pytest.mark.parametrize("reason", ["CANCELED", "ERROR", "INTERRUPTED", "MAX_STEPS_EXCEEDED"])
def test_unsuccessful_stop_does_not_journal(runtime, tmp_path, reason):
    data = {**payload(tmp_path), "terminationReason": reason}
    assert runtime.snapshot(data, tmp_path, tmp_path / ".memsearch") is None


def test_queue_keeps_only_spoken_text(runtime, tmp_path):
    data = payload(tmp_path)
    Path(data["transcriptPath"]).write_text(
        json.dumps(
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "content": "<USER_REQUEST>Question</USER_REQUEST><ADDITIONAL_METADATA>private metadata</ADDITIONAL_METADATA>",
            }
        )
        + "\n"
        + json.dumps(
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "content": "Answer",
                "thinking": "private thought",
                "tool_calls": [{"name": "shell", "args": {"command": "private command"}}],
            }
        )
        + "\n"
    )
    job = runtime.snapshot(data, tmp_path, tmp_path / ".memsearch")
    assert "private" not in job.read_text()


def test_hint_quotes_plugin_and_project_shell_paths(runtime, tmp_path, monkeypatch):
    import shlex

    project = tmp_path / "project's space;$(literal)"
    project.mkdir()
    plugin = tmp_path / "plugin's folder"
    monkeypatch.setattr(runtime, "PLUGIN", plugin)
    result = runtime.hook("session-start", payload(project))
    text = result["injectSteps"][0]["systemMessage"]["systemMessage"]
    command = text.split("Scoped CLI: ")[1].split(" <command>")[0]
    assert shlex.split(command) == [
        "python3",
        str(plugin / "scripts/runtime.py"),
        "cli",
        "--project-dir",
        str(project),
        "--",
    ]


def test_lite_lock_shared_across_projects_and_released_after_failure(runtime, tmp_path, monkeypatch):
    from filelock import FileLock

    database = tmp_path / "shared.db"
    other = tmp_path / "other"
    other.mkdir()
    lock = FileLock(str(database) + ".antigravity.lock")
    with lock:
        monkeypatch.chdir(other)
        with pytest.raises(runtime.LocalDatabaseBusy), runtime.local_db_access("../shared.db", timeout=0.01):
            pytest.fail("Must use the same canonical URI lock across projects")
        # Remote clients do not serialize on a local file.
        with runtime.local_db_access("http://127.0.0.1:19530", timeout=0):
            pass
    with pytest.raises(ValueError), runtime.local_db_access(str(database), timeout=0.01):
        raise ValueError("synthetic interruption")
    with lock.acquire(timeout=0.01):
        pass
