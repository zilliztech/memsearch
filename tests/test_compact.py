from __future__ import annotations

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
    assert captured["model"] == "claude-sonnet-4-5-20250929"
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
        "model": "gemini-2.0-flash",
    }


@pytest.mark.asyncio
async def test_compact_chunks_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        await compact_module.compact_chunks([{"content": "x"}], llm_provider="unknown")
