"""CLI interface for memsearch."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from .config import (
    GLOBAL_CONFIG_PATH,
    PROJECT_CONFIG_PATH,
    ConfigEnvVarError,
    MemSearchConfig,
    config_to_dict,
    get_config_value,
    load_config_file,
    resolve_config,
    save_config,
    set_config_value,
)

try:
    from pymilvus.exceptions import MilvusException
except ImportError:
    MilvusException = Exception


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _safe_resolve_config(overrides: dict | None = None):
    """Resolve config with user-friendly error for missing env vars."""
    try:
        return resolve_config(overrides)
    except ConfigEnvVarError as e:
        click.echo(f"Configuration error: {e}", err=True)
        raise SystemExit(1) from None


# -- CLI param name → dotted config key mapping --
_PARAM_MAP = {
    "provider": "embedding.provider",
    "model": "embedding.model",
    "batch_size": "embedding.batch_size",
    "base_url": "embedding.base_url",
    "api_key": "embedding.api_key",
    "collection": "milvus.collection",
    "milvus_uri": "milvus.uri",
    "milvus_token": "milvus.token",
    "llm_provider": "compact.llm_provider",
    "llm_model": "compact.llm_model",
    "prompt_file": "compact.prompt_file",
    "llm_base_url": "compact.base_url",
    "llm_api_key": "compact.api_key",
    "max_chunk_size": "chunking.max_chunk_size",
    "overlap_lines": "chunking.overlap_lines",
    "debounce_ms": "watch.debounce_ms",
    "reranker_model": "reranker.model",
}


def _build_cli_overrides(**kwargs) -> dict:
    """Map flat CLI params to a nested config override dict.

    Only non-None values are included (None means "not set by user").
    """
    result: dict = {}
    for param, dotted_key in _PARAM_MAP.items():
        val = kwargs.get(param)
        if val is None:
            continue
        section, field = dotted_key.split(".")
        result.setdefault(section, {})[field] = val
    return result


def _cfg_to_memsearch_kwargs(cfg: MemSearchConfig) -> dict:
    """Extract MemSearch constructor kwargs from a resolved config."""
    return {
        "embedding_provider": cfg.embedding.provider,
        "embedding_model": cfg.embedding.model or None,
        "embedding_batch_size": cfg.embedding.batch_size,
        "embedding_base_url": cfg.embedding.base_url or None,
        "embedding_api_key": cfg.embedding.api_key or None,
        "milvus_uri": cfg.milvus.uri,
        "milvus_token": cfg.milvus.token or None,
        "collection": cfg.milvus.collection,
        "max_chunk_size": cfg.chunking.max_chunk_size,
        "overlap_lines": cfg.chunking.overlap_lines,
        "reranker_model": cfg.reranker.model,
    }


def _normalize_compact_source(source: str | None) -> str | None:
    """Normalize compact --source paths to the absolute form used at index time.

    Relative and user-home paths are resolved to match the absolute `source`
    values stored during indexing. Non-path filters are left unchanged.
    """
    if not source:
        return None

    candidate = Path(source).expanduser()
    if candidate.is_absolute() or candidate.exists():
        return str(candidate.resolve())

    return source


# -- Common CLI options --


def _common_options(f):
    """Shared options for commands that create a MemSearch instance."""
    f = click.option("--provider", "-p", default=None, help="Embedding provider.")(f)
    f = click.option("--model", "-m", default=None, help="Override embedding model.")(f)
    f = click.option("--batch-size", default=None, type=int, help="Embedding batch size (0 = provider default).")(f)
    f = click.option("--base-url", default=None, help="OpenAI-compatible API base URL.")(f)
    f = click.option("--api-key", default=None, help="API key for the embedding provider.")(f)
    f = click.option("--collection", "-c", default=None, help="Milvus collection name.")(f)
    f = click.option("--milvus-uri", default=None, help="Milvus connection URI.")(f)
    f = click.option("--milvus-token", default=None, help="Milvus auth token.")(f)
    return f


@click.group()
@click.version_option(package_name="memsearch")
def cli() -> None:
    """memsearch — semantic memory search for markdown knowledge bases."""


@cli.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@_common_options
@click.option("--force", is_flag=True, help="Re-index all files.")
@click.option(
    "--max-chunk-size", default=None, type=click.IntRange(min=1), help="Max chunk size in characters (must be >= 1)."
)
@click.option("--description", default=None, help="Collection description (written on creation only).")
def index(
    paths: tuple[str, ...],
    provider: str | None,
    model: str | None,
    batch_size: int | None,
    base_url: str | None,
    api_key: str | None,
    collection: str | None,
    milvus_uri: str | None,
    milvus_token: str | None,
    force: bool,
    max_chunk_size: int | None,
    description: str | None,
) -> None:
    """Index markdown files from PATHS."""
    from .core import MemSearch

    cfg = _safe_resolve_config(
        _build_cli_overrides(
            provider=provider,
            model=model,
            batch_size=batch_size,
            base_url=base_url,
            api_key=api_key,
            collection=collection,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
            max_chunk_size=max_chunk_size,
        )
    )
    ms = None
    try:
        ms = MemSearch(list(paths), **_cfg_to_memsearch_kwargs(cfg), description=description or "")
        n = _run(ms.index(force=force))
        click.echo(f"Indexed {n} chunks.")
    except MilvusException as e:
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    finally:
        if ms is not None:
            ms.close()


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=None, type=int, help="Number of results.")
@click.option(
    "--source-prefix",
    default=None,
    type=click.Path(),
    help="Only search chunks whose source path starts with this prefix.",
)
@_common_options
@click.option("--reranker-model", default=None, help="Cross-encoder model for reranking (empty string disables).")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON.")
def search(
    query: str,
    top_k: int | None,
    source_prefix: str | None,
    provider: str | None,
    model: str | None,
    batch_size: int | None,
    base_url: str | None,
    api_key: str | None,
    collection: str | None,
    milvus_uri: str | None,
    milvus_token: str | None,
    reranker_model: str | None,
    json_output: bool,
) -> None:
    """Search indexed memory for QUERY."""
    from .core import MemSearch

    cfg = _safe_resolve_config(
        _build_cli_overrides(
            provider=provider,
            model=model,
            batch_size=batch_size,
            base_url=base_url,
            api_key=api_key,
            collection=collection,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
            reranker_model=reranker_model,
        )
    )
    ms = None
    try:
        ms = MemSearch(**_cfg_to_memsearch_kwargs(cfg))
        results = _run(ms.search(query, top_k=top_k or 5, source_prefix=source_prefix))
        if json_output:
            click.echo(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            if not results:
                click.echo("No results found.")
                return
            for i, r in enumerate(results, 1):
                score = r.get("score", 0)
                source = r.get("source", "?")
                heading = r.get("heading", "")
                content = r.get("content", "")
                click.echo(f"\n--- Result {i} (score: {score:.4f}) ---")
                click.echo(f"Source: {source}")
                if heading:
                    click.echo(f"Heading: {heading}")
                if len(content) > 500:
                    click.echo(content[:500])
                    chunk_hash = r.get("chunk_hash", "")
                    click.echo(f"  ... [truncated, run 'memsearch expand {chunk_hash}' for full content]")
                else:
                    click.echo(content)
    except MilvusException as e:
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    finally:
        if ms is not None:
            ms.close()


# ======================================================================
# Expand command (progressive disclosure L2)
#
# Shows the full heading section around a chunk, used by the Claude Code
# plugin's progressive disclosure workflow:
#   L1: `search` returns chunk snippets
#   L2: `expand` shows the full heading section around a chunk
#
# Works with memsearch's anchor comments embedded in memory files:
#   <!-- session:UUID turn:UUID transcript:PATH -->
# ======================================================================


@cli.command()
@click.argument("chunk_hash")
@click.option("--section/--no-section", default=True, help="Show full heading section (default).")
@click.option("--lines", "-n", default=None, type=int, help="Show N lines before/after instead of full section.")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON.")
@_common_options
def expand(
    chunk_hash: str,
    section: bool,
    lines: int | None,
    json_output: bool,
    provider: str | None,
    model: str | None,
    batch_size: int | None,
    base_url: str | None,
    api_key: str | None,
    collection: str | None,
    milvus_uri: str | None,
    milvus_token: str | None,
) -> None:
    """Expand a memory chunk to show full context. [Claude Code plugin: L2]

    Look up CHUNK_HASH in the index, then read the source markdown file
    to return the surrounding context (full heading section by default).

    Part of the progressive disclosure workflow (search -> expand -> transcript).
    """
    from .store import MilvusStore

    cfg = _safe_resolve_config(
        _build_cli_overrides(
            provider=provider,
            model=model,
            batch_size=batch_size,
            base_url=base_url,
            api_key=api_key,
            collection=collection,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
        )
    )
    store = None
    try:
        store = MilvusStore(
            uri=cfg.milvus.uri,
            token=cfg.milvus.token or None,
            collection=cfg.milvus.collection,
            dimension=None,
        )
        chunks = store.query(filter_expr=f'chunk_hash == "{chunk_hash}"')
        if not chunks:
            click.echo(f"Chunk not found: {chunk_hash}", err=True)
            sys.exit(1)

        chunk = chunks[0]
        source = chunk["source"]
        start_line = chunk["start_line"]
        end_line = chunk["end_line"]
        heading = chunk.get("heading", "")
        heading_level = chunk.get("heading_level", 0)

        source_path = Path(source)
        if not source_path.exists():
            click.echo(f"Source file not found: {source}", err=True)
            sys.exit(1)

        all_lines = source_path.read_text(encoding="utf-8").splitlines()

        if lines is not None:
            # Show N lines before/after the chunk
            ctx_start = max(0, start_line - 1 - lines)
            ctx_end = min(len(all_lines), end_line + lines)
            expanded = "\n".join(all_lines[ctx_start:ctx_end])
            expanded_start = ctx_start + 1
            expanded_end = ctx_end
        else:
            # Show full section under the same heading
            expanded, expanded_start, expanded_end = _extract_section(
                all_lines,
                start_line,
                heading_level,
            )

        # Parse any anchor comments in the expanded text
        import re

        anchor_match = re.search(
            r"<!--\s*session:(\S+)\s+turn:(\S+)\s+transcript:(\S+)\s*-->",
            expanded,
        )
        anchor = {}
        if anchor_match:
            anchor = {
                "session": anchor_match.group(1),
                "turn": anchor_match.group(2),
                "transcript": anchor_match.group(3),
            }

        if json_output:
            result = {
                "chunk_hash": chunk_hash,
                "source": source,
                "heading": heading,
                "start_line": expanded_start,
                "end_line": expanded_end,
                "content": expanded,
            }
            if anchor:
                result["anchor"] = anchor
            click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Source: {source} (lines {expanded_start}-{expanded_end})")
            if heading:
                click.echo(f"Heading: {heading}")
            if anchor:
                click.echo(f"Session: {anchor['session']}  Turn: {anchor['turn']}")
                click.echo(f"Transcript: {anchor['transcript']}")
            click.echo(f"\n{expanded}")
    except MilvusException as e:
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    finally:
        if store is not None:
            store.close()


def _extract_section(
    all_lines: list[str],
    start_line: int,
    heading_level: int,
) -> tuple[str, int, int]:
    """Extract the full section containing the chunk.

    Walks backward to find the section heading, then forward to the next
    heading of equal or higher level (or EOF).
    """
    # Find section start — walk backward to the heading
    section_start = start_line - 1  # 0-indexed
    if heading_level > 0:
        for i in range(start_line - 2, -1, -1):
            line = all_lines[i]
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                if level <= heading_level:
                    section_start = i
                    break

    # Find section end — walk forward to the next heading of same or higher level
    section_end = len(all_lines)
    if heading_level > 0:
        for i in range(start_line, len(all_lines)):
            line = all_lines[i]
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                if level <= heading_level:
                    section_end = i
                    break

    content = "\n".join(all_lines[section_start:section_end])
    return content, section_start + 1, section_end


@cli.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@_common_options
@click.option("--debounce-ms", default=None, type=int, help="Debounce delay in ms.")
@click.option(
    "--max-chunk-size", default=None, type=click.IntRange(min=1), help="Max chunk size in characters (must be >= 1)."
)
@click.option("--description", default=None, help="Collection description (written on creation only).")
def watch(
    paths: tuple[str, ...],
    provider: str | None,
    model: str | None,
    batch_size: int | None,
    base_url: str | None,
    api_key: str | None,
    collection: str | None,
    milvus_uri: str | None,
    milvus_token: str | None,
    debounce_ms: int | None,
    max_chunk_size: int | None,
    description: str | None,
) -> None:
    """Watch PATHS for markdown changes and auto-index."""
    from .core import MemSearch

    cfg = _safe_resolve_config(
        _build_cli_overrides(
            provider=provider,
            model=model,
            batch_size=batch_size,
            base_url=base_url,
            api_key=api_key,
            collection=collection,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
            debounce_ms=debounce_ms,
            max_chunk_size=max_chunk_size,
        )
    )
    ms = None
    watcher = None
    try:
        ms = MemSearch(list(paths), **_cfg_to_memsearch_kwargs(cfg), description=description or "")

        # Initial index: ensure existing files are indexed before watching
        n = _run(ms.index())
        if n:
            click.echo(f"Indexed {n} chunks.")

        def _on_event(event_type: str, summary: str, file_path) -> None:
            click.echo(summary)

        click.echo(f"Watching {len(paths)} path(s) for changes... (Ctrl+C to stop)")
        watcher = ms.watch(on_event=_on_event, debounce_ms=cfg.watch.debounce_ms)
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nStopping watcher.")
    except MilvusException as e:
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    finally:
        if watcher is not None:
            watcher.stop()
        if ms is not None:
            ms.close()


@cli.command()
@click.option("--source", "-s", default=None, help="Only compact chunks from this source.")
@click.option(
    "--output-dir", "-o", default=None, type=click.Path(), help="Directory to write the compact summary into."
)
@click.option("--llm-provider", default=None, help="LLM for summarization.")
@click.option("--llm-model", default=None, help="Override LLM model.")
@click.option("--llm-base-url", default=None, help="OpenAI-compatible base URL for the LLM.")
@click.option("--llm-api-key", default=None, help="API key for the LLM provider.")
@click.option("--prompt", default=None, help="Custom prompt template (must contain {chunks}).")
@click.option("--prompt-file", default=None, type=click.Path(exists=True), help="Read prompt template from file.")
@_common_options
def compact(
    source: str | None,
    output_dir: str | None,
    llm_provider: str | None,
    llm_model: str | None,
    llm_base_url: str | None,
    llm_api_key: str | None,
    prompt: str | None,
    prompt_file: str | None,
    provider: str | None,
    model: str | None,
    batch_size: int | None,
    base_url: str | None,
    api_key: str | None,
    collection: str | None,
    milvus_uri: str | None,
    milvus_token: str | None,
) -> None:
    """Compress stored memories into a summary."""
    from .core import MemSearch

    cfg = _safe_resolve_config(
        _build_cli_overrides(
            provider=provider,
            model=model,
            batch_size=batch_size,
            base_url=base_url,
            api_key=api_key,
            collection=collection,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
            llm_provider=llm_provider,
            llm_model=llm_model,
            prompt_file=prompt_file,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
        )
    )

    prompt_template = prompt
    # Resolve prompt: CLI --prompt > prompts.compact > compact.prompt_file > built-in
    if not prompt_template and cfg.prompts.compact:
        prompt_template = Path(cfg.prompts.compact).expanduser().read_text(encoding="utf-8")
    if not prompt_template and cfg.compact.prompt_file:
        prompt_template = Path(cfg.compact.prompt_file).read_text(encoding="utf-8")

    # Resolve LLM settings: [llm] > [compact] (deprecated) > defaults
    eff_provider = cfg.llm.provider or cfg.compact.llm_provider
    eff_model = cfg.llm.model or cfg.compact.llm_model or None
    eff_base_url = cfg.llm.base_url or cfg.compact.base_url or None
    eff_api_key = cfg.llm.api_key or cfg.compact.api_key or None

    normalized_source = _normalize_compact_source(source)

    ms = None
    try:
        ms = MemSearch(**_cfg_to_memsearch_kwargs(cfg))
        summary = _run(
            ms.compact(
                source=normalized_source,
                llm_provider=eff_provider,
                llm_model=eff_model,
                prompt_template=prompt_template,
                output_dir=output_dir,
                llm_base_url=eff_base_url,
                llm_api_key=eff_api_key,
            )
        )
        if summary:
            click.echo("Compact complete. Summary:\n")
            click.echo(summary)
        elif normalized_source:
            click.echo(f"No chunks matched source: {normalized_source}")
        else:
            click.echo("No chunks to compact.")
    except MilvusException as e:
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    finally:
        if ms is not None:
            ms.close()


@cli.command()
@click.option("--collection", "-c", default=None, help="Milvus collection name.")
@click.option("--milvus-uri", default=None, help="Milvus connection URI.")
@click.option("--milvus-token", default=None, help="Milvus auth token.")
def stats(
    collection: str | None,
    milvus_uri: str | None,
    milvus_token: str | None,
) -> None:
    """Show statistics about the index."""
    from .store import MilvusStore

    cfg = _safe_resolve_config(
        _build_cli_overrides(
            collection=collection,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
        )
    )
    store = None
    try:
        store = MilvusStore(
            uri=cfg.milvus.uri,
            token=cfg.milvus.token or None,
            collection=cfg.milvus.collection,
            dimension=None,
        )
        count = store.count()
        click.echo(f"Total indexed chunks: {count}")
    except MilvusException as e:
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    finally:
        if store is not None:
            store.close()


@cli.command()
@click.option("--collection", "-c", default=None, help="Milvus collection name.")
@click.option("--milvus-uri", default=None, help="Milvus connection URI.")
@click.option("--milvus-token", default=None, help="Milvus auth token.")
@click.confirmation_option(prompt="This will delete all indexed data. Continue?")
def reset(
    collection: str | None,
    milvus_uri: str | None,
    milvus_token: str | None,
) -> None:
    """Drop all indexed data."""
    from .store import MilvusStore

    cfg = _safe_resolve_config(
        _build_cli_overrides(
            collection=collection,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
        )
    )
    store = None
    try:
        store = MilvusStore(
            uri=cfg.milvus.uri,
            token=cfg.milvus.token or None,
            collection=cfg.milvus.collection,
            dimension=None,
        )
        store.drop()
        click.echo("Dropped collection.")
    except MilvusException as e:
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    finally:
        if store is not None:
            store.close()


# ======================================================================
# Config command group
# ======================================================================


@cli.group("config")
def config_group() -> None:
    """Manage memsearch configuration."""


@config_group.command("init")
@click.option("--project", is_flag=True, help="Write to .memsearch.toml (project-level) instead of global.")
def config_init(project: bool) -> None:
    """Interactive configuration wizard."""

    target = PROJECT_CONFIG_PATH if project else GLOBAL_CONFIG_PATH
    load_config_file(target)
    current = resolve_config()

    result: dict = {}

    click.echo("memsearch configuration wizard")
    click.echo(f"Writing to: {target}\n")

    # Milvus
    click.echo("── Milvus ──")
    result["milvus"] = {}
    result["milvus"]["uri"] = click.prompt(
        "  Milvus URI",
        default=current.milvus.uri,
    )
    result["milvus"]["token"] = click.prompt(
        "  Milvus token (empty for none)",
        default=current.milvus.token,
    )
    result["milvus"]["collection"] = click.prompt(
        "  Collection name",
        default=current.milvus.collection,
    )

    # Embedding
    click.echo("\n── Embedding ──")
    result["embedding"] = {}
    _embedding_defaults = {
        "openai": "text-embedding-3-small",
        "google": "gemini-embedding-001",
        "voyage": "voyage-3-lite",
        "jina": "jina-embeddings-v4",
        "mistral": "mistral-embed",
        "ollama": "nomic-embed-text",
        "local": "all-MiniLM-L6-v2",
        "onnx": "gpahal/bge-m3-onnx-int8",
    }
    result["embedding"]["provider"] = click.prompt(
        "  Provider (openai/google/voyage/jina/mistral/ollama/local/onnx)",
        default=current.embedding.provider,
    )
    _emb_provider = result["embedding"]["provider"]
    _emb_model_default = current.embedding.model or _embedding_defaults.get(_emb_provider, "")
    result["embedding"]["model"] = click.prompt(
        "  Model",
        default=_emb_model_default,
    )
    result["embedding"]["base_url"] = click.prompt(
        "  Base URL (empty for default, or env:VAR_NAME)",
        default=current.embedding.base_url,
    )
    result["embedding"]["api_key"] = click.prompt(
        "  API key (empty for env default, or env:VAR_NAME)",
        default=current.embedding.api_key,
    )

    # Chunking
    click.echo("\n── Chunking ──")
    result["chunking"] = {}
    result["chunking"]["max_chunk_size"] = click.prompt(
        "  Max chunk size (chars)",
        default=current.chunking.max_chunk_size,
        type=int,
    )
    result["chunking"]["overlap_lines"] = click.prompt(
        "  Overlap lines",
        default=current.chunking.overlap_lines,
        type=int,
    )

    # Watch
    click.echo("\n── Watch ──")
    result["watch"] = {}
    result["watch"]["debounce_ms"] = click.prompt(
        "  Debounce (ms)",
        default=current.watch.debounce_ms,
        type=int,
    )

    # LLM
    click.echo("\n── LLM (for compact & plugin summarization) ──")
    click.echo("  Leave empty to let plugins use their own agent model.")
    _llm_defaults = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-haiku-4-5-20251001",
        "gemini": "gemini-2.0-flash",
    }
    result["llm"] = {}
    result["llm"]["provider"] = click.prompt(
        "  Provider (empty/openai/anthropic/gemini)",
        default=current.llm.provider,
    )
    _llm_provider = result["llm"]["provider"]
    _llm_model_default = current.llm.model or _llm_defaults.get(_llm_provider, "")
    result["llm"]["model"] = click.prompt(
        "  Model",
        default=_llm_model_default,
    )
    result["llm"]["base_url"] = click.prompt(
        "  Base URL (empty for default, or env:VAR_NAME)",
        default=current.llm.base_url,
    )
    result["llm"]["api_key"] = click.prompt(
        "  API key (empty for env default, or env:VAR_NAME)",
        default=current.llm.api_key,
    )

    # Prompts
    click.echo("\n── Prompts ──")
    click.echo("  Leave empty to use built-in defaults.")
    result["prompts"] = {}
    result["prompts"]["compact"] = click.prompt(
        "  Compact prompt file",
        default=current.prompts.compact,
    )
    result["prompts"]["summarize"] = click.prompt(
        "  Summarize prompt file (for plugin session notes)",
        default=current.prompts.summarize,
    )

    save_config(result, target)
    click.echo(f"\nConfig saved to {target}")


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--project", is_flag=True, help="Write to project config.")
def config_set(key: str, value: str, project: bool) -> None:
    """Set a config value (e.g. memsearch config set milvus.uri http://host:19530)."""
    try:
        set_config_value(key, value, project=project)
        target = PROJECT_CONFIG_PATH if project else GLOBAL_CONFIG_PATH
        click.echo(f"Set {key} = {value} in {target}")
    except (KeyError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@config_group.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Get a resolved config value (e.g. memsearch config get milvus.uri)."""
    try:
        val = get_config_value(key)
        click.echo(val)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@config_group.command("list")
@click.option("--resolved", "mode", flag_value="resolved", default=True, help="Show fully resolved config (default).")
@click.option("--global", "mode", flag_value="global", help="Show global config file only.")
@click.option("--project", "mode", flag_value="project", help="Show project config file only.")
def config_list(mode: str) -> None:
    """Show configuration."""
    import tomli_w

    if mode == "global":
        data = load_config_file(GLOBAL_CONFIG_PATH)
        label = f"Global ({GLOBAL_CONFIG_PATH})"
    elif mode == "project":
        data = load_config_file(PROJECT_CONFIG_PATH)
        label = f"Project ({PROJECT_CONFIG_PATH})"
    else:
        cfg = resolve_config()
        data = config_to_dict(cfg)
        label = "Resolved (all sources merged)"

    click.echo(f"# {label}\n")
    if data:
        click.echo(tomli_w.dumps(data))
    else:
        click.echo("(empty)")
