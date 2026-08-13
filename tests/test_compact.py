from __future__ import annotations

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
async def test_anthropic_compact_skips_leading_thinking_block(monkeypatch) -> None:
    """A ThinkingBlock before the TextBlock must not crash the response parse.

    Extended-thinking models can emit a thinking block first. That block carries
    no ``.text``, so indexing ``content[0]`` raised AttributeError and dropped
    the whole compact result.
    """

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="thinking", thinking="considering..."),
                    SimpleNamespace(type="text", text="summary"),
                ]
            )

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic))

    assert await compact_module._compact_anthropic("prompt", "claude-test") == "summary"


@pytest.mark.asyncio
async def test_anthropic_compact_returns_empty_when_no_text_block(monkeypatch) -> None:
    """A response carrying no text block yields "" rather than raising."""

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking="...")])

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic))

    assert await compact_module._compact_anthropic("prompt", "claude-test") == ""


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
    assert captured["model"] == "claude-sonnet-4-6"
    assert "memory chunk" in captured["prompt"]


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
