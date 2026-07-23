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
from .index_report import IndexFailure, format_error
from .index_state import (
    record_index_error,
    record_index_report,
    record_index_started,
    resolve_index_state_path,
)
from .io import read_utf8_text_replace

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


def _cfg_to_memsearch_kwargs(
    cfg: MemSearchConfig,
    *,
    extra_ignore_files: tuple[str, ...] = (),
    extra_exclude: tuple[str, ...] = (),
) -> dict:
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
        "ignore_files": _merge_unique(cfg.indexing.ignore_files, extra_ignore_files),
        "exclude": _merge_unique(cfg.indexing.exclude, extra_exclude),
        "reranker_model": cfg.reranker.model,
    }


def _merge_unique(configured: list[str], extra: tuple[str, ...]) -> list[str]:
    """Append CLI list values to config values while preserving order."""
    return list(dict.fromkeys([*configured, *extra]))


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


def _plugin_summarize_config(cfg: MemSearchConfig, plugin: str) -> dict:
    """Return TOML-facing summarize config for a plugin platform."""
    plugins = config_to_dict(cfg).get("plugins", {})
    plugin_cfg = plugins.get(plugin)
    if not isinstance(plugin_cfg, dict):
        raise KeyError(f"Unknown plugin platform: {plugin}")
    summarize = plugin_cfg.get("summarize", {})
    if not isinstance(summarize, dict):
        return {}
    return summarize


def _load_plugin_summarize_prompt(cfg: MemSearchConfig, agent_name: str) -> str:
    """Load the plugin summarize prompt template."""
    if cfg.prompts.summarize:
        prompt_path = Path(cfg.prompts.summarize).expanduser()
        if prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8").replace("{{AGENT_NAME}}", agent_name)
    return (
        "You are a third-person note-taker. You will receive a transcript of ONE conversation turn "
        f"between User and {agent_name}.\n\n"
        "Record what happened as factual third-person notes. Output 2-10 bullet points, each starting with '- '. "
        "Use 'User' for the user. First bullet: what User asked or wanted. Remaining bullets: what was done, "
        f"found, changed, configured, tested, explained, decided, or could not be completed by {agent_name}. "
        "Mandatory language rule: write every bullet in the same primary language as the [User] text. "
        "If User mixes languages, use the dominant user-facing language. "
        "Be specific when useful: mention important files read or edited, searches or research performed, "
        "refactors, commands or tests run, key findings, and concrete outcomes. Prefer the final user-visible "
        "outcome over low-level transcript mechanics. Do NOT answer User's question yourself. Output ONLY "
        "bullet points."
    )


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


def _indexing_options(f):
    """Shared opt-in ignore options for index and watch."""
    f = click.option(
        "--ignore-file",
        "ignore_files",
        multiple=True,
        metavar="NAME",
        help="Discover an ignore filename within each index root (repeatable).",
    )(f)
    f = click.option(
        "--exclude",
        "exclude_patterns",
        multiple=True,
        metavar="PATTERN",
        help="Add a gitignore-style exclusion pattern (repeatable).",
    )(f)
    return f


@click.group()
@click.version_option(package_name="memsearch")
def cli() -> None:
    """memsearch — semantic memory search for markdown knowledge bases."""


@cli.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@_common_options
@_indexing_options
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
    ignore_files: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    force: bool,
    max_chunk_size: int | None,
    description: str | None,
) -> None:
    """Index markdown files from PATHS."""
    from .core import MemSearch

    state_path = resolve_index_state_path(paths)
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
        record_index_started(
            state_path,
            operation="index",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        ms = MemSearch(
            list(paths),
            **_cfg_to_memsearch_kwargs(
                cfg,
                extra_ignore_files=ignore_files,
                extra_exclude=exclude_patterns,
            ),
            description=description or "",
        )
        report = _run(ms.index_with_report(force=force))
        record_index_report(
            state_path,
            report,
            operation="index",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        click.echo(f"Indexed {report.indexed_chunks} chunks.")
    except MilvusException as e:
        record_index_error(
            state_path,
            e,
            operation="index",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    except Exception as e:
        record_index_error(
            state_path,
            e,
            operation="index",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        raise
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

        all_lines = read_utf8_text_replace(source_path).splitlines()

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
@_indexing_options
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
    ignore_files: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    debounce_ms: int | None,
    max_chunk_size: int | None,
    description: str | None,
) -> None:
    """Watch PATHS for markdown changes and auto-index."""
    from .core import MemSearch

    state_path = resolve_index_state_path(paths)
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
        record_index_started(
            state_path,
            operation="watch",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        ms = MemSearch(
            list(paths),
            **_cfg_to_memsearch_kwargs(
                cfg,
                extra_ignore_files=ignore_files,
                extra_exclude=exclude_patterns,
            ),
            description=description or "",
        )

        # Initial index: ensure existing files are indexed before watching
        report = _run(ms.index_with_report())
        record_index_report(
            state_path,
            report,
            operation="watch",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        if report.indexed_chunks:
            click.echo(f"Indexed {report.indexed_chunks} chunks.")

        def _on_event(event_type: str, summary: str, file_path) -> None:
            click.echo(summary)

        def _on_error(event_type: str, error: BaseException, file_path) -> None:
            record_index_error(
                state_path,
                error,
                operation=f"watch:{event_type}",
                paths=(str(file_path),),
                collection=cfg.milvus.collection,
                milvus_uri=cfg.milvus.uri,
                status="degraded",
                failed_files=(IndexFailure(path=str(file_path), error=format_error(error)),),
            )

        click.echo(f"Watching {len(paths)} path(s) for changes... (Ctrl+C to stop)")
        watcher = ms.watch(on_event=_on_event, on_error=_on_error, debounce_ms=cfg.watch.debounce_ms)
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nStopping watcher.")
    except MilvusException as e:
        record_index_error(
            state_path,
            e,
            operation="watch",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        click.echo(f"Milvus error (code {e.code}): {e.message}", err=True)
        raise SystemExit(1) from None
    except Exception as e:
        record_index_error(
            state_path,
            e,
            operation="watch",
            paths=paths,
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        raise
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
@click.option("--plugin", required=True, help="Plugin platform name (claude-code, codex, opencode, openclaw).")
@click.option("--agent-name", default="", help="Agent display name for the summarize prompt.")
def summarize(plugin: str, agent_name: str) -> None:
    """Summarize stdin using a configured memsearch-managed LLM provider."""
    from .compact import summarize_text

    cfg = _safe_resolve_config()
    summarize_cfg = _plugin_summarize_config(cfg, plugin)
    provider_name = str(summarize_cfg.get("provider") or "").strip()
    if not provider_name or provider_name == "native":
        click.echo(
            f"Plugin {plugin!r} is configured for native summarization; no memsearch-managed provider selected.",
            err=True,
        )
        raise SystemExit(2)

    provider_cfg = cfg.llm.providers.get(provider_name)
    if provider_cfg is None:
        click.echo(f"Unknown LLM provider {provider_name!r}. Configure [llm.providers.{provider_name}].", err=True)
        raise SystemExit(1)

    provider_type = provider_cfg.type or provider_name
    model = str(summarize_cfg.get("model") or provider_cfg.model or "").strip() or None
    transcript = sys.stdin.read()
    if not transcript.strip():
        return

    prompt_agent_name = agent_name or plugin
    system_prompt = _load_plugin_summarize_prompt(cfg, prompt_agent_name)
    prompt = f"{system_prompt}\n\nTranscript:\n{transcript}"
    try:
        summary = _run(
            summarize_text(
                prompt,
                llm_provider=provider_type,
                model=model,
                base_url=provider_cfg.base_url or None,
                api_key=provider_cfg.api_key or None,
            )
        )
    except (ConfigEnvVarError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None

    if summary:
        click.echo(summary)


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
@click.option("--project", is_flag=True, help="Write allowlisted local indexing keys to .memsearch.toml.")
def config_init(project: bool) -> None:
    """Interactive configuration wizard."""

    target = PROJECT_CONFIG_PATH if project else GLOBAL_CONFIG_PATH
    existing = load_config_file(target)
    current = resolve_config()

    result: dict = {}

    click.echo("memsearch configuration wizard")
    click.echo(f"Writing to: {target}\n")

    existing_indexing = existing.get("indexing", {})
    if not isinstance(existing_indexing, dict):
        existing_indexing = {}
    indexing_defaults = {
        "ignore_files": existing_indexing.get("ignore_files", [".gitignore"]),
        "exclude": existing_indexing.get("exclude", []),
    }

    if project:
        click.echo("Project config is limited to low-risk local indexing keys.")
        result["milvus"] = {}
        result["milvus"]["collection"] = click.prompt(
            "  Collection name",
            default=current.milvus.collection,
        )

        result["embedding"] = {}
        result["embedding"]["batch_size"] = click.prompt(
            "  Embedding batch size (0 = provider default)",
            default=current.embedding.batch_size,
            type=int,
        )

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

        result["indexing"] = indexing_defaults

        click.echo("\n── Watch ──")
        result["watch"] = {}
        result["watch"]["debounce_ms"] = click.prompt(
            "  Debounce (ms)",
            default=current.watch.debounce_ms,
            type=int,
        )

        save_config(result, target)
        click.echo(f"\nConfig saved to {target}")
        return

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

    result["indexing"] = indexing_defaults

    # Watch
    click.echo("\n── Watch ──")
    result["watch"] = {}
    result["watch"]["debounce_ms"] = click.prompt(
        "  Debounce (ms)",
        default=current.watch.debounce_ms,
        type=int,
    )

    # LLM
    click.echo("\n── LLM (for memsearch compact) ──")
    click.echo("  Plugin summarization uses plugins.<platform>.summarize.model.")
    _llm_defaults = {
        "openai": "gpt-5-mini",
        "anthropic": "claude-sonnet-4-6",
        "gemini": "gemini-3-flash-preview",
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

    # Plugin summarize model overrides
    click.echo("\n── Plugin summarize routing ──")
    click.echo("  Leave provider empty/native to keep each plugin's current native summarizer.")
    result["plugins"] = {
        "claude-code": {"summarize": {}, "project_review": {}, "user_profile": {}},
        "codex": {"summarize": {}, "project_review": {}, "user_profile": {}},
        "opencode": {"summarize": {}, "project_review": {}, "user_profile": {}},
        "openclaw": {"summarize": {}, "project_review": {}, "user_profile": {}},
    }
    result["plugins"]["claude-code"]["summarize"]["enabled"] = click.confirm(
        "  Claude Code automatic summaries enabled",
        default=current.plugins.claude_code.summarize.enabled,
    )
    result["plugins"]["claude-code"]["summarize"]["provider"] = click.prompt(
        "  Claude Code summarize provider",
        default=current.plugins.claude_code.summarize.provider,
    )
    result["plugins"]["claude-code"]["summarize"]["model"] = click.prompt(
        "  Claude Code summarize model",
        default=current.plugins.claude_code.summarize.model,
    )
    result["plugins"]["codex"]["summarize"]["enabled"] = click.confirm(
        "  Codex automatic summaries enabled",
        default=current.plugins.codex.summarize.enabled,
    )
    result["plugins"]["codex"]["summarize"]["provider"] = click.prompt(
        "  Codex summarize provider",
        default=current.plugins.codex.summarize.provider,
    )
    result["plugins"]["codex"]["summarize"]["model"] = click.prompt(
        "  Codex summarize model",
        default=current.plugins.codex.summarize.model,
    )
    result["plugins"]["opencode"]["summarize"]["enabled"] = click.confirm(
        "  OpenCode automatic summaries enabled",
        default=current.plugins.opencode.summarize.enabled,
    )
    result["plugins"]["opencode"]["summarize"]["provider"] = click.prompt(
        "  OpenCode summarize provider",
        default=current.plugins.opencode.summarize.provider,
    )
    result["plugins"]["opencode"]["summarize"]["model"] = click.prompt(
        "  OpenCode summarize model",
        default=current.plugins.opencode.summarize.model,
    )
    result["plugins"]["openclaw"]["summarize"]["enabled"] = click.confirm(
        "  OpenClaw automatic summaries enabled",
        default=current.plugins.openclaw.summarize.enabled,
    )
    result["plugins"]["openclaw"]["summarize"]["provider"] = click.prompt(
        "  OpenClaw summarize provider",
        default=current.plugins.openclaw.summarize.provider,
    )
    result["plugins"]["openclaw"]["summarize"]["model"] = click.prompt(
        "  OpenClaw summarize model",
        default=current.plugins.openclaw.summarize.model,
    )

    click.echo("\n── Advanced maintenance ──")
    click.echo("  Disabled by default. Configure provider/model if you enable these tasks.")
    for key, label, current_platform in [
        ("claude-code", "Claude Code", current.plugins.claude_code),
        ("codex", "Codex", current.plugins.codex),
        ("opencode", "OpenCode", current.plugins.opencode),
        ("openclaw", "OpenClaw", current.plugins.openclaw),
    ]:
        for task_name, task_label in [("project_review", "project review"), ("user_profile", "user profile")]:
            task = getattr(current_platform, task_name)
            section = result["plugins"][key][task_name]
            section["enabled"] = click.confirm(f"  {label} {task_label} enabled", default=task.enabled)
            section["provider"] = click.prompt(f"  {label} {task_label} provider", default=task.provider)
            section["model"] = click.prompt(f"  {label} {task_label} model", default=task.model)
            section["min_interval_hours"] = click.prompt(
                f"  {label} {task_label} min interval hours",
                default=task.min_interval_hours,
                type=int,
            )
            section["input_dir"] = click.prompt(f"  {label} {task_label} input dir", default=task.input_dir)
            section["output_file"] = click.prompt(f"  {label} {task_label} output file", default=task.output_file)

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
    result["prompts"]["project_review"] = click.prompt(
        "  Project review prompt file",
        default=current.prompts.project_review,
    )
    result["prompts"]["user_profile"] = click.prompt(
        "  User profile prompt file",
        default=current.prompts.user_profile,
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
        # Lowercase booleans so shell consumers (e.g. hooks comparing against
        # "false") don't trip over Python's "True"/"False" repr.
        click.echo(str(val).lower() if isinstance(val, bool) else val)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@config_group.command("list")
@click.option("--resolved", "mode", flag_value="resolved", default=True, help="Show fully resolved config (default).")
@click.option("--global", "mode", flag_value="global", help="Show global config file only.")
@click.option("--project", "mode", flag_value="project", help="Show project config file only.")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON.")
def config_list(mode: str, json_output: bool) -> None:
    """Show configuration."""
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

    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False))
        return

    import tomli_w

    click.echo(f"# {label}\n")
    if data:
        click.echo(tomli_w.dumps(data))
    else:
        click.echo("(empty)")


@cli.group("skills")
def skills_group() -> None:
    """Distill, capture, list, and install candidate skills from memory (procedural memory)."""


@skills_group.command("distill")
@click.option("--plugin", required=True, help="Plugin platform name (claude-code, codex, opencode, openclaw).")
@click.option("--force", is_flag=True, help="Run even if input is unchanged or not yet due.")
def skills_distill(plugin: str, force: bool) -> None:
    """Mine recent memory journals for recurring workflows using a configured API provider.

    This is an explicit invocation, so it runs regardless of the
    ``memory_to_skill.enabled`` flag (which only gates the background pass).
    Requires an API provider: the default ``native`` provider drives the host
    agent and only works from the background pass — for on-demand mining, use the
    ``/memory-to-skill`` skill, which reasons over the journals directly.
    """
    from . import skills as skills_mod

    cfg = _safe_resolve_config()
    task_cfg = skills_mod._get_task_config(cfg, plugin)
    provider = ((task_cfg.provider if task_cfg else "") or "native").strip()
    if provider == "native":
        click.echo(
            "Standalone 'skills distill' needs an API provider; the default 'native' provider only works "
            "via the background pass. For on-demand mining use the /memory-to-skill skill, or configure a "
            f"provider, e.g.: memsearch config set plugins.{plugin}.memory_to_skill.provider <name>",
            err=True,
        )
        raise SystemExit(2)
    result = skills_mod.distill(platform=plugin, cfg=cfg, force=force, require_enabled=False)
    if result.skipped:
        click.echo(f"Skipped: {result.reason or result.action}")
        return
    changed = result.created + result.updated
    if changed:
        click.echo(f"Distilled {len(changed)} candidate skill(s): {', '.join(changed)}")
    else:
        click.echo("No new candidate skills.")


@skills_group.command("add")
@click.option("--name", required=True, help="Skill name (slugified to the command and directory name).")
@click.option("--description", required=True, help="One line: what the skill does and when it should trigger.")
@click.option(
    "--body-file",
    required=True,
    type=click.File("r"),
    help="File containing the SKILL.md body (markdown, no frontmatter). Use - for stdin.",
)
def skills_add(name: str, description: str, body_file) -> None:
    """Persist an agent-drafted skill as a candidate (manual capture path).

    The agent supplies the content; this writes a structurally-correct candidate
    (frontmatter, meta.json, git commit) without any LLM call.
    """
    from . import skills as skills_mod

    try:
        slug = skills_mod.add(name, description, body_file.read())
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    click.echo(f"Added candidate skill: {slug}")
    click.echo(f"Install it with: memsearch skills install {slug} --path <dir>")


@skills_group.command("list")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON.")
def skills_list(json_output: bool) -> None:
    """List candidate and installed skills in the store."""
    from . import skills as skills_mod

    _project_root, mem_root = skills_mod.resolve_roots(None, None)
    candidates = skills_mod.list_candidates(mem_root)
    if json_output:
        click.echo(json.dumps(candidates, indent=2, ensure_ascii=False))
        return
    if not candidates:
        click.echo("No skills in the store yet.")
        return
    for meta in candidates:
        occ = meta.get("occurrences")
        occ_text = f", seen {occ}x" if isinstance(occ, int) else ""
        pending_reason = meta.get("pending_reason")
        pending_text = ""
        if pending_reason == "new":
            pending_text = ", install ready"
        elif pending_reason == "updated":
            pending_text = ", update ready"
        click.echo(
            f"- {meta.get('name')} [{meta.get('status', 'candidate')}{occ_text}{pending_text}] "
            f"- {meta.get('description', '')}"
        )


@skills_group.command("status")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--hint", is_flag=True, help="Print only the startup hint when candidate skill versions are pending.")
def skills_status(json_output: bool, hint: bool) -> None:
    """Show whether candidate skills need review and installation."""
    from . import skills as skills_mod

    _project_root, mem_root = skills_mod.resolve_roots(None, None)
    summary = skills_mod.candidate_review_summary(mem_root)
    if json_output:
        click.echo(json.dumps(summary, indent=2, ensure_ascii=False))
        return
    if hint:
        rendered = skills_mod.format_candidate_hint(summary)
        if rendered:
            click.echo(rendered)
        return
    if summary["pending_count"] == 0:
        click.echo("No candidate skill versions pending install.")
        return
    click.echo(skills_mod.format_candidate_hint(summary))
    click.echo(f"New: {summary['new_count']}; updated: {summary['updated_count']}.")


@skills_group.command("install")
@click.argument("name")
@click.option("--path", "paths", multiple=True, help="Install destination (repeatable). E.g. .claude/skills")
def skills_install(name: str, paths: tuple[str, ...]) -> None:
    """Install a candidate skill into one or more agent skill directories."""
    from . import skills as skills_mod

    if not paths:
        click.echo("Error: no --path given. Specify where to install, e.g. --path .claude/skills", err=True)
        raise SystemExit(2)
    try:
        installed = skills_mod.install(name, list(paths))
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    for dest in installed:
        click.echo(f"Installed: {dest}")


@cli.command("transcript")
@click.argument("path", type=click.Path())
@click.option("--turn", "-t", default=None, help="Target turn/session id (prefix match); shows surrounding context.")
@click.option("--context", "-c", default=3, type=int, help="Turns of context to show before/after --turn.")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON.")
def transcript_cmd(path: str, turn: str | None, context: int, json_output: bool) -> None:
    """Show original conversation turns, with tool calls, from a session transcript.

    L3 of progressive recall (search -> expand -> transcript): pass the transcript
    path from a journal anchor to recover the exact commands, flags, and paths the
    journal summary drops. Auto-detects Claude Code / Codex / OpenClaw formats.
    """
    from . import transcript as transcript_mod

    try:
        turns = transcript_mod.parse_transcript(path)
    except transcript_mod.UnknownTranscriptFormat:
        click.echo(
            "Unrecognized transcript format. Read the file directly to locate the relevant turns.",
            err=True,
        )
        raise SystemExit(3) from None
    except (FileNotFoundError, OSError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
    turns = transcript_mod.select_turns(turns, turn, context)
    if json_output:
        payload = [
            {
                "role": t.role,
                "uuid": t.uuid,
                "text": t.text,
                "tools": [{"name": tc.name, "command": tc.command, "output": tc.output} for tc in t.tools],
            }
            for t in turns
        ]
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        click.echo(transcript_mod.format_turns(turns))
