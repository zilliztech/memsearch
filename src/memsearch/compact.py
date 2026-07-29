"""Memory compact — compress and summarize chunks using an LLM.

Supports OpenAI (default), OpenAI-compatible, Anthropic, Gemini, and MiniMax as
LLM backends.  API keys are read from environment variables:
    OPENAI_API_KEY / OPENAI_BASE_URL
    MINIMAX_API_KEY
    ANTHROPIC_API_KEY
    GOOGLE_API_KEY
"""

from __future__ import annotations

import os
from typing import Any

from .config import resolve_env_ref, resolve_llm_provider_settings

COMPACT_PROMPT = """\
You are a knowledge compression assistant. Given the following chunks of text \
from a knowledge base, create a concise but comprehensive summary that preserves \
all key facts, decisions, code patterns, and actionable insights.

Chunks:
{chunks}

Write a clear, well-structured markdown summary. Use headings and bullet points. \
Preserve technical details, code snippets, and specific decisions."""


async def compact_chunks(
    chunks: list[dict[str, Any]],
    *,
    llm_provider: str = "openai",
    model: str | None = None,
    prompt_template: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Compress *chunks* into a summary using an LLM.

    Parameters
    ----------
    chunks:
        List of chunk dicts (must contain ``"content"`` key).
    llm_provider:
        One of ``"openai"``, ``"openai-compatible"``, ``"anthropic"``,
        ``"gemini"``, or ``"minimax"``.
    model:
        Override the default model for the provider.
    prompt_template:
        Custom prompt template.  Must contain ``{chunks}`` placeholder.
        Defaults to the built-in ``COMPACT_PROMPT``.
    base_url:
        Custom base URL for OpenAI-compatible and Anthropic API endpoints.
    api_key:
        API key for the LLM provider.  Used by the OpenAI-compatible and
        Anthropic routes.

    Returns
    -------
    str
        The compressed summary markdown.
    """
    if not chunks:
        return ""
    combined = "\n\n---\n\n".join(c["content"] for c in chunks)
    template = prompt_template or COMPACT_PROMPT
    if "{chunks}" not in template:
        raise ValueError("prompt_template must include the {chunks} placeholder")
    prompt = template.format(chunks=combined)

    llm_provider, model, base_url, api_key = resolve_llm_provider_settings(llm_provider, model, base_url, api_key)
    provider = "openai" if llm_provider == "openai-compatible" else llm_provider
    if provider == "openai":
        return await _compact_openai(prompt, model or "gpt-5-mini", base_url=base_url, api_key=api_key)
    elif provider == "anthropic":
        return await _compact_anthropic(prompt, model or "claude-sonnet-4-6", base_url=base_url, api_key=api_key)
    elif provider == "gemini":
        return await _compact_gemini(prompt, model or "gemini-3-flash-preview")
    else:
        raise ValueError(
            f"Unknown LLM provider {llm_provider!r}. Available: openai, openai-compatible, anthropic, gemini, minimax"
        )


async def summarize_text(
    prompt: str,
    *,
    llm_provider: str,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Summarize preformatted text with a memsearch-managed LLM provider."""
    llm_provider, model, base_url, api_key = resolve_llm_provider_settings(llm_provider, model, base_url, api_key)
    provider = "openai" if llm_provider == "openai-compatible" else llm_provider
    if provider == "openai":
        return await _compact_openai(prompt, model or "gpt-5-mini", base_url=base_url, api_key=api_key)
    if provider == "anthropic":
        return await _compact_anthropic(prompt, model or "claude-sonnet-4-6", base_url=base_url, api_key=api_key)
    if provider == "gemini":
        return await _compact_gemini(prompt, model or "gemini-3-flash-preview")
    raise ValueError(
        f"Unknown LLM provider type {llm_provider!r}. Available: openai, openai-compatible, anthropic, gemini, minimax"
    )


async def _compact_openai(prompt: str, model: str, *, base_url: str | None = None, api_key: str | None = None) -> str:
    import openai

    kwargs: dict = {}
    resolved_base_url = resolve_env_ref(base_url) if base_url else os.environ.get("OPENAI_BASE_URL")
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    if api_key:
        kwargs["api_key"] = resolve_env_ref(api_key)

    client = openai.AsyncOpenAI(**kwargs)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


async def _compact_anthropic(
    prompt: str, model: str, *, base_url: str | None = None, api_key: str | None = None
) -> str:
    import anthropic

    kwargs: dict = {}
    if base_url:
        kwargs["base_url"] = resolve_env_ref(base_url)
    if api_key:
        kwargs["api_key"] = resolve_env_ref(api_key)
    client = anthropic.AsyncAnthropic(**kwargs)  # falls back to ANTHROPIC_API_KEY when api_key is unset
    resp = await client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


async def _compact_gemini(prompt: str, model: str) -> str:
    from google import genai

    client = genai.Client()  # reads GOOGLE_API_KEY
    resp = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
    )
    return resp.text or ""
