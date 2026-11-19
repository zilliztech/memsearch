"""Query-time synthesis over retrieved memories (the reflect layer).

``MemSearch.search`` returns ranked chunks; ``synthesize`` adds a conclusion
step: retrieve the top-N chunks for a question, hand them to a
memsearch-managed LLM provider (the same routing ``compact`` uses), and
return a short answer grounded in the memories.
"""

from __future__ import annotations

from typing import Any

from .compact import summarize_text

_NO_RESULTS_PREFIX = "No relevant memories found for"
_DEFAULT_MAX_CONTEXT_CHARS = 16000
_TRUNCATION_MARKER = "\n[... further retrieved memories omitted ...]\n"


async def synthesize(
    mem: Any,
    question: str,
    *,
    top_k: int = 8,
    max_context_chars: int = _DEFAULT_MAX_CONTEXT_CHARS,
    llm_provider: str = "openai",
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_api_key: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> str:
    """Answer ``question`` from the top-K memories, via a managed LLM.

    Empty retrieval short-circuits without calling any LLM, so the answer is
    either grounded in retrieved memories or an explicit "nothing found" —
    never a hallucinated bridge over an empty result set. LLM failures
    propagate from :func:`summarize_text` (they are never swallowed).
    """
    if top_k <= 0:
        raise ValueError(f"top_k must be >= 1, got {top_k}")
    results = await mem.search(question, top_k=top_k, since=since, until=until)
    if not results:
        return f"{_NO_RESULTS_PREFIX}: {question}"

    sections: list[str] = []
    used = 0
    truncated = False
    for i, chunk in enumerate(results, 1):
        source = str(chunk.get("source", "?"))
        heading = str(chunk.get("heading", "") or "")
        content = str(chunk.get("content", "") or "")
        block = f"<<<MEMORY {i} | source={source} | heading={heading}>>>\n{content}\n<<<END MEMORY {i}>>>"
        if used + len(block) > max_context_chars:
            truncated = True
            break
        sections.append(block)
        used += len(block) + 1
    context = "\n".join(sections)
    if truncated:
        context += _TRUNCATION_MARKER

    prompt = (
        "You answer questions using the user's memory journals. Ground every claim in the "
        "memories between the <<<MEMORY>>> markers; if they do not contain the answer, say so "
        "plainly. Do not invent facts. Answer in the language of the question.\n\n"
        f"Question: {question}\n\n"
        "Retrieved memories:\n\n"
        f"{context}\n\n"
        "Answer:"
    )
    return await summarize_text(
        prompt,
        llm_provider=llm_provider,
        model=llm_model,
        base_url=llm_base_url,
        api_key=llm_api_key,
    )
