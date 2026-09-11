"""Memory compact — compress and summarize chunks using an LLM.

Supports OpenAI (default), Anthropic, and Gemini as LLM backends.
API keys are read from environment variables:
    OPENAI_API_KEY / OPENAI_BASE_URL
    ANTHROPIC_API_KEY
    GOOGLE_API_KEY
"""

from __future__ import annotations

import os
import time
from typing import Any

from .config import resolve_env_ref

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
        One of ``"openai"``, ``"anthropic"``, ``"gemini"``.
    model:
        Override the default model for the provider.
    prompt_template:
        Custom prompt template.  Must contain ``{chunks}`` placeholder.
        Defaults to the built-in ``COMPACT_PROMPT``.
    base_url:
        Custom base URL for OpenAI-compatible API endpoints.  Only used
        when *llm_provider* is ``"openai"``.
    api_key:
        API key for the LLM provider.  Only used when *llm_provider* is
        ``"openai"``.

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

    started = time.monotonic()
    try:
        if llm_provider == "openai":
            result = await _compact_openai(prompt, model or "gpt-5-mini", base_url=base_url, api_key=api_key)
        elif llm_provider == "anthropic":
            result = await _compact_anthropic(prompt, model or "claude-sonnet-4-6")
        elif llm_provider == "gemini":
            result = await _compact_gemini(prompt, model or "gemini-3-flash-preview")
        else:
            raise ValueError(f"Unknown LLM provider {llm_provider!r}. Available: openai, anthropic, gemini")
    except Exception as exc:  # audit before re-raising
        _audit_call(
            source="compact",
            provider=llm_provider,
            model=model,
            status="error",
            started=started,
            error=exc,
        )
        raise
    _audit_call(
        source="compact",
        provider=llm_provider,
        model=model,
        status="ok",
        started=started,
    )
    return result


async def summarize_text(
    prompt: str,
    *,
    llm_provider: str,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    audit_source: str = "summarize",
    audit_context: str | None = None,
) -> str:
    """Summarize preformatted text with a memsearch-managed LLM provider."""
    provider = "openai" if llm_provider == "openai-compatible" else llm_provider
    started = time.monotonic()
    try:
        if provider == "openai":
            result = await _compact_openai(prompt, model or "gpt-5-mini", base_url=base_url, api_key=api_key)
        elif provider == "anthropic":
            result = await _compact_anthropic(prompt, model or "claude-sonnet-4-6")
        elif provider == "gemini":
            result = await _compact_gemini(prompt, model or "gemini-3-flash-preview")
        else:
            raise ValueError(
                f"Unknown LLM provider type {llm_provider!r}. Available: openai, openai-compatible, anthropic, gemini"
            )
    except Exception as exc:  # audit before re-raising
        _audit_call(
            source=audit_source,
            provider=provider,
            model=model,
            status="error",
            started=started,
            error=exc,
            context=audit_context,
        )
        raise
    _audit_call(
        source=audit_source,
        provider=provider,
        model=model,
        status="ok",
        started=started,
        context=audit_context,
    )
    return result


def _audit_call(
    *,
    source: str,
    provider: str,
    model: str | None,
    status: str,
    started: float,
    error: BaseException | None = None,
    context: str | None = None,
) -> None:
    """Record one background LLM call to the audit log (best-effort)."""
    from .audit import record

    enabled = True
    try:
        from .config import resolve_config

        enabled = resolve_config().llm_audit.enabled
    except Exception:
        enabled = True
    record(
        source=source,
        provider=f"{provider}/{model}" if model else provider,
        status=status,
        duration_ms=int((time.monotonic() - started) * 1000),
        output_tokens=None,  # provider SDKs used here do not expose usage
        error=f"{type(error).__name__}: {error}" if error else None,
        context=context,
        enabled=enabled,
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


async def _compact_anthropic(prompt: str, model: str) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY
    resp = await client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    # A model may emit a ThinkingBlock before the TextBlock, in which case
    # content[0] has no .text and indexing it raises AttributeError. Pick the
    # first text block instead of assuming its position.
    for block in resp.content:
        if block.type == "text":
            return block.text
    raise ValueError("Anthropic response contained no text block")


async def _compact_gemini(prompt: str, model: str) -> str:
    from google import genai

    client = genai.Client()  # reads GOOGLE_API_KEY
    resp = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
    )
    return resp.text or ""
