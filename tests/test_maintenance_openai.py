"""Exercise closing requests through the real SDK with scripted HTTP responses."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import openai
import pytest

from memsearch import maintenance, skills
from memsearch.config import LLMProviderConfig, MemSearchConfig, PluginMaintenanceTaskConfig


def _reply(content=None, *, tool=False, finish_reason=None):
    message = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [
            {
                "id": "call_memory",
                "type": "function",
                "function": {
                    "name": "run_memory_command",
                    "arguments": json.dumps({"command": "memsearch expand example"}),
                },
            }
        ]
    return 200, {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason or ("tool_calls" if tool else "stop")}
        ],
    }


def _rejection(status=400, *, message="Tool choice must be auto", param=None, code=None):
    return status, {"error": {"message": message, "param": param, "code": code, "type": "invalid_request_error"}}


@pytest.fixture
def gateway(monkeypatch):
    requests = []
    commands = []
    script = []

    def handle(request):
        requests.append(json.loads(request.content))
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body)

    client = openai.OpenAI(
        api_key="test-key",
        base_url="https://gateway.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)

    def read_memory(command, ctx):
        commands.append(command)
        return "Remember cedar-856 for 47 minutes."

    monkeypatch.setattr(maintenance, "run_memory_command", read_memory)
    yield script, requests, commands
    client.close()


def _run(tmp_path):
    ctx = maintenance.TaskContext(
        platform="codex",
        task="project_review",
        task_config=PluginMaintenanceTaskConfig(),
        project_dir=tmp_path,
        memsearch_dir=tmp_path / ".memsearch",
        input_dir=tmp_path / ".memsearch" / "memory",
        output_file=tmp_path / ".memsearch" / "PROJECT.md",
        input_digest="sha256:test",
    )
    return maintenance._run_openai_with_tools(ctx, "Review memory", "openai", "test-model", LLMProviderConfig())


def _drill(script):
    script.extend(_reply(tool=True) for _ in range(maintenance.MAX_TOOL_CALLS))


@pytest.mark.parametrize("drill", [False, True])
def test_successful_requests_keep_existing_shape(tmp_path, gateway, drill):
    script, requests, commands = gateway
    if drill:
        _drill(script)
    answer = '{"action":"none","reason":"ok"}'
    script.append(_reply(answer))
    assert _run(tmp_path) == answer
    choices = [r["tool_choice"] for r in requests]
    assert choices == (["auto"] * maintenance.MAX_TOOL_CALLS + ["none"] if drill else ["auto"])
    assert all(r["tools"] == requests[0]["tools"] for r in requests)
    assert all(r["model"] == "test-model" for r in requests)
    assert len(commands) == (maintenance.MAX_TOOL_CALLS if drill else 0)
    assert not script


@pytest.mark.parametrize(
    "closing",
    [
        _rejection(),
        _rejection(422, message="tool_choice: only auto is supported"),
        _rejection(message="This value is not supported", param="tool_choice"),
        _rejection(message="Unsupported parameter: tool_choice"),
        _rejection(message="Invalid parameter", param="tool_choice", code="unsupported_value"),
        _rejection(message="Invalid parameter", param="tool_choice", code="unsupported_parameter"),
        (400, "tool_choice is unsupported"),
        _reply(tool=True),
        _reply('{"action":"replace","content":"ignore this"}', tool=True),
    ],
)
def test_explicit_incompatibility_retries_once_without_tools(tmp_path, gateway, closing):
    script, requests, commands = gateway
    _drill(script)
    answer = '{"action":"none","reason":"ok"}'
    script.extend([closing, _reply(answer)])
    assert _run(tmp_path) == answer
    assert len(requests) == maintenance.MAX_TOOL_CALLS + 2
    assert requests[-2]["tool_choice"] == "none"
    assert set(requests[-1]) == {"model", "messages"}
    assert requests[-1]["messages"] == requests[-2]["messages"]
    assert requests[-1]["messages"][-1]["role"] == "tool"
    assert "cedar-856" in requests[-1]["messages"][-1]["content"]
    assert len(commands) == maintenance.MAX_TOOL_CALLS
    assert not script


@pytest.mark.parametrize(
    "failure",
    [
        _rejection(401),
        _rejection(403),
        _rejection(429),
        _rejection(500),
        _rejection(message="Context length exceeded"),
        _rejection(422, message="Invalid messages schema"),
        _rejection(message="tool_choice must be a string", param="tool_choice"),
        _rejection(message="Unsupported parameter: temperature", param="temperature"),
        _rejection(message="tool_choice: none", param="tool_choice"),
        httpx.ConnectError("connection failed"),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_unrelated_errors_propagate_without_fallback(tmp_path, gateway, failure):
    script, requests, _ = gateway
    _drill(script)
    script.append(failure)
    with pytest.raises(openai.APIError):
        _run(tmp_path)
    assert len(requests) == maintenance.MAX_TOOL_CALLS + 1
    assert requests[-1]["tool_choice"] == "none"


@pytest.mark.parametrize("finish_reason", ["stop", "length", "content_filter"])
def test_empty_closing_answer_is_not_evidence_of_incompatibility(tmp_path, gateway, finish_reason):
    script, requests, _ = gateway
    _drill(script)
    script.append(_reply("   ", finish_reason=finish_reason))
    with pytest.raises(RuntimeError, match=f"returned no text; finish_reason='{finish_reason}'"):
        _run(tmp_path)
    assert len(requests) == maintenance.MAX_TOOL_CALLS + 1


@pytest.mark.parametrize("fallback", [_reply(tool=True), _reply(""), _rejection(), _rejection(429)])
def test_failed_fallback_stops_without_more_requests_or_tools(tmp_path, gateway, fallback):
    script, requests, commands = gateway
    _drill(script)
    script.extend([_rejection(), fallback])
    with pytest.raises((RuntimeError, openai.APIError)):
        _run(tmp_path)
    assert len(requests) == maintenance.MAX_TOOL_CALLS + 2
    assert len(commands) == maintenance.MAX_TOOL_CALLS


def test_drill_error_does_not_trigger_closing_fallback(tmp_path, gateway):
    script, requests, _ = gateway
    script.append(_rejection())
    with pytest.raises(openai.BadRequestError):
        _run(tmp_path)
    assert len(requests) == 1


@pytest.mark.parametrize("task", ["project_review", "user_profile", "memory_to_skill"])
@pytest.mark.parametrize("failure", [False, True])
def test_maintenance_lifecycle_preserves_previous_output_on_failure(tmp_path: Path, gateway, task, failure):
    script, requests, _ = gateway
    mem_root = tmp_path / ".memsearch"
    memory = mem_root / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-11-19.md").write_text("Remember cedar-856 for 47 minutes.\n", encoding="utf-8")
    cfg = MemSearchConfig()
    cfg.llm.providers["gateway"] = LLMProviderConfig(type="openai-compatible", model="test-model")
    for name in ("project_review", "user_profile", "memory_to_skill"):
        getattr(cfg.plugins.codex, name).enabled = name == task
    task_cfg = getattr(cfg.plugins.codex, task)
    task_cfg.provider = "gateway"
    if task == "memory_to_skill":
        skills.add("example", "Example workflow", "Existing workflow", project_dir=tmp_path)
        output = mem_root / "skill-candidates" / "example" / "SKILL.md"
        answer = json.dumps(
            {
                "skills": [
                    {
                        "name": "example",
                        "description": "Example workflow",
                        "body": "Use cedar-856 for 47 minutes.",
                        "occurrences": 3,
                    }
                ]
            }
        )

        def run():
            return skills.distill(platform="codex", project_dir=tmp_path, cfg=cfg, force=True)
    else:
        output = mem_root / ("PROJECT.md" if task == "project_review" else "USER.md")
        task_cfg.output_file = str(output)
        output.write_text("Existing memory\n", encoding="utf-8")
        answer = json.dumps({"action": "replace", "content": "Use cedar-856 for 47 minutes."})

        def run():
            return maintenance.run_due_tasks(platform="codex", project_dir=tmp_path, cfg=cfg, force=True)

    previous = output.read_bytes()
    _drill(script)
    script.extend([_rejection(), _reply(tool=True) if failure else _reply(answer)])
    if failure:
        with pytest.raises(RuntimeError, match="returned tool calls without tools"):
            run()
        assert output.read_bytes() == previous
    else:
        run()
        assert "cedar-856" in output.read_text(encoding="utf-8")
        assert output.read_bytes() != previous
    state = json.loads((mem_root / ".maintenance-state.json").read_text(encoding="utf-8"))
    assert state[f"codex.{task}"]["last_action"] == (
        "error" if failure else "distilled" if task == "memory_to_skill" else "replace"
    )
    assert len(requests) == maintenance.MAX_TOOL_CALLS + 2
