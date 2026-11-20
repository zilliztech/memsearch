"""Exercise MiniMax defaults and explicit selections through the real SDK serializer."""

from __future__ import annotations

import json

import httpx
import openai
import pytest
from click.testing import CliRunner

from memsearch import compact
from memsearch.cli import cli
from memsearch.config import (
    MINIMAX_LLM_MODELS,
    MemSearchConfig,
    PluginMaintenanceTaskConfig,
    load_config_file,
    save_config,
)
from memsearch.maintenance import TaskContext, run_task_llm


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch):
    for name in (
        "MINIMAX_REGION",
        "MINIMAX_API_REGION",
        "MINIMAX_API_BASE",
        "MINIMAX_BASE_URL",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-only-key")


@pytest.mark.parametrize("model", ["", "MiniMax-M3", "MiniMax-M2.7", "custom-model"])
def test_config_init_default_and_saved_model(monkeypatch, tmp_path, model):
    config_path = tmp_path / "config.toml"
    save_config({"llm": {"provider": "minimax", "model": model}}, config_path)
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", config_path)
    monkeypatch.setattr("memsearch.cli.GLOBAL_CONFIG_PATH", config_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "missing.toml")
    monkeypatch.setattr("click.prompt", lambda text, **kwargs: kwargs["default"])
    monkeypatch.setattr("click.confirm", lambda text, **kwargs: kwargs["default"])

    result = CliRunner().invoke(cli, ["config", "init"])

    assert result.exit_code == 0, result.output
    assert load_config_file(config_path)["llm"]["model"] == (model or "MiniMax-M3.1-Flash")


def completion(message):
    return httpx.Response(
        200,
        json={
            "id": "test-completion",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        },
    )


@pytest.mark.parametrize("entrypoint", ["compact", "summarize"])
@pytest.mark.parametrize("region,host", [("global", "api.minimax.io"), ("cn", "api.minimaxi.com")])
@pytest.mark.parametrize("model", [None, "MiniMax-M3", "MiniMax-M2.7", "custom-model"])
async def test_summary_serialized_request(monkeypatch, entrypoint, region, host, model):
    requests = []

    def handler(request):
        requests.append(request)
        return completion({"role": "assistant", "content": "summary"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        sdk = openai.AsyncOpenAI
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: sdk(http_client=http_client, **kwargs))
        monkeypatch.setenv("MINIMAX_REGION", region)
        if entrypoint == "compact":
            result = await compact.compact_chunks([{"content": "memory"}], llm_provider="minimax", model=model)
        else:
            result = await compact.summarize_text("memory", llm_provider="minimax", model=model)

    assert result == "summary"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == f"https://{host}/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-only-key"
    body = json.loads(request.content)
    assert body["model"] == (model or "MiniMax-M3.1-Flash")
    assert "memory" in body["messages"][0]["content"]
    assert set(body) == {"model", "messages"}


@pytest.mark.parametrize("model", ["", "MiniMax-M3", "MiniMax-M2.7", "custom-model"])
def test_saved_summary_config_reaches_transport(monkeypatch, tmp_path, model):
    config_path = tmp_path / "config.toml"
    save_config({"plugins": {"codex": {"summarize": {"provider": "minimax", "model": model}}}}, config_path)
    original = config_path.read_text()
    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", config_path)
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", tmp_path / "missing.toml")
    requests = []

    def handler(request):
        requests.append(request)
        return completion({"role": "assistant", "content": "summary"})

    sdk = openai.AsyncOpenAI
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: sdk(http_client=http_client, **kwargs))
    result = CliRunner().invoke(cli, ["summarize", "--plugin", "codex"], input="[User]: remember this")

    assert result.exit_code == 0, result.output
    assert json.loads(requests[0].content)["model"] == (model or "MiniMax-M3.1-Flash")
    assert config_path.read_text() == original


@pytest.mark.parametrize("region", ["global", "cn"])
@pytest.mark.parametrize("model", ["", "MiniMax-M3", "MiniMax-M2.7", "custom-model"])
def test_maintenance_serialized_tool_history(monkeypatch, tmp_path, region, model):
    monkeypatch.setenv("MINIMAX_REGION", region)
    bodies = []
    tool_message = {
        "role": "assistant",
        "content": None,
        "reasoning_details": [{"type": "reasoning.text", "text": "Inspect memory"}],
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "run_memory_command", "arguments": '{"command":""}'},
            }
        ],
    }

    def handler(request):
        bodies.append(json.loads(request.content))
        host = "api.minimax.io" if region == "global" else "api.minimaxi.com"
        assert str(request.url) == f"https://{host}/v1/chat/completions"
        return completion(tool_message if len(bodies) == 1 else {"role": "assistant", "content": "done"})

    task_config = PluginMaintenanceTaskConfig(provider="minimax", model=model)
    ctx = TaskContext(
        platform="codex",
        task="project_review",
        task_config=task_config,
        project_dir=tmp_path,
        memsearch_dir=tmp_path / ".memsearch",
        input_dir=tmp_path,
        output_file=tmp_path / "PROJECT.md",
        input_digest="test",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        sdk = openai.OpenAI
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: sdk(http_client=http_client, **kwargs))
        assert run_task_llm(ctx, "memory", MemSearchConfig()) == "done"

    assert len(bodies) == 2
    assert all(body["model"] == (model or "MiniMax-M3.1-Flash") for body in bodies)
    assert bodies[1]["messages"][1]["tool_calls"] == tool_message["tool_calls"]
    assert bodies[1]["messages"][1]["reasoning_details"] == tool_message["reasoning_details"]
    assert bodies[1]["messages"][2]["tool_call_id"] == "call_1"
    assert all(set(body) == {"model", "messages", "tools", "tool_choice"} for body in bodies)


async def test_custom_endpoint_and_non_minimax_provider_are_preserved(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return completion({"role": "assistant", "content": "summary"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        sdk = openai.AsyncOpenAI
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: sdk(http_client=http_client, **kwargs))
        for provider, model in [("minimax", "custom-model"), ("openai", "gpt-5-mini")]:
            await compact.summarize_text(
                "memory", llm_provider=provider, model=model, base_url="https://custom.example/v1", api_key="custom-key"
            )

    assert [json.loads(request.content)["model"] for request in requests] == ["custom-model", "gpt-5-mini"]
    assert all(str(request.url) == "https://custom.example/v1/chat/completions" for request in requests)
    assert all(request.headers["authorization"] == "Bearer custom-key" for request in requests)
    assert MINIMAX_LLM_MODELS == ("MiniMax-M3.1-Flash", "MiniMax-M3")
