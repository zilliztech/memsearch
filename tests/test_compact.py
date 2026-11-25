from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from memsearch import compact as compact_module


@pytest.mark.asyncio
async def test_compact_chunks_returns_empty_string_for_empty_input() -> None:
    assert await compact_module.compact_chunks([]) == ""


@pytest.mark.asyncio
async def test_compact_chunks_dispatches_to_openai(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    async def fake_openai(prompt: str, model: str, *, base_url: str | None = None, api_key: str | None = None) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        return "openai-summary"

    monkeypatch.setattr(compact_module, "_compact_openai", fake_openai)

    result = await compact_module.compact_chunks(
        [{"content": "alpha"}, {"content": "beta"}],
        llm_provider="openai",
        model="gpt-test",
        base_url="https://example.invalid/v1",
        api_key="env:OPENAI_API_KEY",
    )

    assert result == "openai-summary"
    assert captured == {
        "prompt": compact_module.COMPACT_PROMPT.format(chunks="alpha\n\n---\n\nbeta"),
        "model": "gpt-test",
        "base_url": "https://example.invalid/v1",
        "api_key": "env:OPENAI_API_KEY",
    }


@pytest.mark.asyncio
async def test_openai_compact_uses_default_temperature(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="summary"))])

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))

    result = await compact_module._compact_openai("prompt", "gpt-5-mini")

    assert result == "summary"
    assert captured["model"] == "gpt-5-mini"
    assert "temperature" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        [SimpleNamespace(type="text", text="summary")],
        [
            SimpleNamespace(type="thinking", thinking="considering...", signature="sig"),
            SimpleNamespace(type="text", text="summary"),
        ],
        [
            SimpleNamespace(type="thinking", thinking="considering...", signature="sig"),
            SimpleNamespace(type="redacted_thinking", data="redacted"),
            SimpleNamespace(type="text", text="summary"),
        ],
    ],
    ids=["text-first", "thinking-first", "multiple-non-text-blocks"],
)
async def test_anthropic_compact_returns_first_text_block(monkeypatch, content) -> None:
    """Anthropic responses may contain non-text blocks before their text."""

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(content=content)

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic))

    assert await compact_module._compact_anthropic("prompt", "claude-test") == "summary"


@pytest.mark.asyncio
async def test_anthropic_compact_raises_when_no_text_block(monkeypatch) -> None:
    """A successful compact must not silently accept a response without text."""

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="thinking", thinking="...", signature="sig"),
                    SimpleNamespace(type="redacted_thinking", data="redacted"),
                ]
            )

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic))

    with pytest.raises(ValueError, match="Anthropic response contained no text block"):
        await compact_module._compact_anthropic("prompt", "claude-test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "block, missing_attribute",
    [
        (SimpleNamespace(text="summary"), "type"),
        (SimpleNamespace(type="text"), "text"),
    ],
)
async def test_anthropic_compact_rejects_malformed_blocks(monkeypatch, block, missing_attribute) -> None:
    """Malformed SDK objects must remain visible as protocol errors."""

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(content=[block])

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic))

    with pytest.raises(AttributeError, match=missing_attribute):
        await compact_module._compact_anthropic("prompt", "claude-test")


@pytest.mark.asyncio
async def test_compact_chunks_dispatches_to_anthropic(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_anthropic(prompt: str, model: str) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return "anthropic-summary"

    monkeypatch.setattr(compact_module, "_compact_anthropic", fake_anthropic)

    result = await compact_module.compact_chunks(
        [{"content": "memory chunk"}],
        llm_provider="anthropic",
    )

    assert result == "anthropic-summary"
    assert captured["model"] == "claude-sonnet-5-5"
    assert "memory chunk" in captured["prompt"]


@pytest.mark.asyncio
async def test_summarize_text_dispatches_to_anthropic(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_anthropic(prompt: str, model: str) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return "anthropic-note"

    monkeypatch.setattr(compact_module, "_compact_anthropic", fake_anthropic)

    result = await compact_module.summarize_text("note text", llm_provider="anthropic")

    assert result == "anthropic-note"
    assert captured == {"prompt": "note text", "model": "claude-sonnet-5-5"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["summarize", "compact"])
@pytest.mark.parametrize("model", [None, "claude-sonnet-5-5", "claude-sonnet-4-6", "custom-model"])
async def test_anthropic_summary_request_thinking_policy(monkeypatch, operation, model) -> None:
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "text", "text": "memory summary"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        )

    async with anthropic.AsyncAnthropic(
        api_key="test-key",
        base_url="https://example.invalid",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: client)
        if operation == "summarize":
            result = await compact_module.summarize_text("Remember this.", llm_provider="anthropic", model=model)
        else:
            result = await compact_module.compact_chunks(
                [{"content": "Remember this."}], llm_provider="anthropic", model=model
            )

    assert result == "memory summary"
    assert len(requests) == 1
    body = requests[0]
    assert body["model"] == (model or "claude-sonnet-5-5")
    assert body["max_tokens"] == 4096
    assert "tools" not in body
    if model in (None, "claude-sonnet-5-5"):
        assert body["thinking"] == {"type": "between_tools"}
    else:
        assert "thinking" not in body


@pytest.mark.asyncio
async def test_compact_chunks_dispatches_to_gemini(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_gemini(prompt: str, model: str) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return "gemini-summary"

    monkeypatch.setattr(compact_module, "_compact_gemini", fake_gemini)

    result = await compact_module.compact_chunks(
        [{"content": "memory chunk"}],
        llm_provider="gemini",
        prompt_template="Summarize:\n{chunks}",
    )

    assert result == "gemini-summary"
    assert captured == {
        "prompt": "Summarize:\nmemory chunk",
        "model": "gemini-3-flash-preview",
    }


@pytest.mark.asyncio
async def test_compact_chunks_rejects_prompt_without_chunks_placeholder() -> None:
    with pytest.raises(ValueError, match=r"prompt_template must include the \{chunks\} placeholder"):
        await compact_module.compact_chunks(
            [{"content": "x"}],
            prompt_template="Summarize the memory carefully.",
        )


@pytest.mark.asyncio
async def test_compact_chunks_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        await compact_module.compact_chunks([{"content": "x"}], llm_provider="unknown")
