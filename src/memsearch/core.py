"""MemSearch — main orchestrator class."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .watcher import FileWatcher

from .chunker import Chunk, chunk_markdown, clean_content_for_embedding, compute_chunk_id
from .compact import compact_chunks
from .embeddings import EmbeddingProvider, get_provider
from .index_report import IndexFailure, IndexReport, format_error
from .io import read_utf8_text_replace
from .scanner import ScannedFile, scan_paths, should_index_path
from .store import MilvusStore

logger = logging.getLogger(__name__)


class MemSearch:
    """High-level API for semantic memory search.

    Parameters
    ----------
    paths:
        Directories / files to index.
    embedding_provider:
        Name of the embedding backend (``"openai"``, ``"google"``, etc.).
    embedding_model:
        Override the default model for the chosen provider.
    milvus_uri:
        Milvus connection URI.  A local ``*.db`` path uses Milvus Lite,
        ``http://host:port`` connects to a Milvus server, and a
        ``https://*.zillizcloud.com`` URL connects to Zilliz Cloud.
    milvus_token:
        Authentication token for Milvus server or Zilliz Cloud.
        Not needed for Milvus Lite (local).
    collection:
        Milvus collection name.  Use different names to isolate
        agents sharing the same Milvus server.
    ignore_files:
        Ignore filenames to discover within each directory index root, such
        as ``[".gitignore"]``. Empty by default for backward compatibility.
    exclude:
        Additional gitignore-style patterns applied relative to each index
        root after discovered ignore-file rules.
    """

    def __init__(
        self,
        paths: list[str | Path] | None = None,
        *,
        embedding_provider: str = "openai",
        embedding_model: str | None = None,
        embedding_batch_size: int = 0,
        embedding_base_url: str | None = None,
        embedding_api_key: str | None = None,
        milvus_uri: str = "~/.memsearch/milvus.db",
        milvus_token: str | None = None,
        collection: str = "memsearch_chunks",
        description: str = "",
        max_chunk_size: int = 1500,
        overlap_lines: int = 2,
        ignore_files: list[str] | None = None,
        exclude: list[str] | None = None,
        reranker_model: str = "",
    ) -> None:
        self._paths = [str(p) for p in (paths or [])]
        self._max_chunk_size = max_chunk_size
        self._overlap_lines = overlap_lines
        self._ignore_files = list(ignore_files or [])
        self._exclude = list(exclude or [])
        self._embedder: EmbeddingProvider = get_provider(
            embedding_provider,
            model=embedding_model,
            batch_size=embedding_batch_size,
            base_url=embedding_base_url,
            api_key=embedding_api_key,
        )
        self._store = MilvusStore(
            uri=milvus_uri,
            token=milvus_token,
            collection=collection,
            dimension=self._embedder.dimension,
            description=description,
        )
        self._reranker_model = reranker_model

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index(self, *, force: bool = False) -> int:
        """Scan paths and index all markdown files.

        Returns the number of chunks indexed.  Also removes chunks for
        files that no longer exist on disk (deleted-file cleanup).
        """
        report = await self.index_with_report(force=force)
        return report.indexed_chunks

    async def index_with_report(self, *, force: bool = False) -> IndexReport:
        """Scan paths and index all markdown files with structured status."""
        files = scan_paths(
            self._paths,
            ignore_files=self._ignore_files,
            exclude=self._exclude,
        )
        total = 0
        failed_files: list[IndexFailure] = []
        active_sources: set[str] = set()
        for f in files:
            active_sources.add(str(f.path))
            try:
                n = await self._index_file(f, force=force)
                total += n
            except Exception as exc:
                failed_files.append(IndexFailure(path=str(f.path), error=format_error(exc)))
                logger.exception("Failed to index %s, skipping", f.path)

        # Clean up deleted files only inside directory roots from this run.
        # Explicit file paths are partial updates and must not prune unrelated
        # sources from the collection.
        cleanup_roots = _cleanup_roots_for_paths(self._paths)
        if cleanup_roots:
            indexed_sources = self._store.indexed_sources()
            for source in indexed_sources:
                if source not in active_sources and _source_under_any_root(source, cleanup_roots):
                    self._store.delete_by_source(source)
                    logger.info("Removed stale chunks for deleted file: %s", source)

        if failed_files:
            logger.warning(
                "Indexed %d chunks from %d files (%d files failed)",
                total,
                len(files) - len(failed_files),
                len(failed_files),
            )
        else:
            logger.info("Indexed %d chunks from %d files", total, len(files))
        return IndexReport(
            indexed_chunks=total,
            total_files=len(files),
            indexed_files=len(files) - len(failed_files),
            failed_files=tuple(failed_files),
        )

    async def index_file(self, path: str | Path) -> int:
        """Index a single file.  Returns number of chunks."""
        p = Path(path).expanduser().resolve()
        _st = p.stat()
        sf = ScannedFile(path=p, mtime=_st.st_mtime, size=_st.st_size)
        return await self._index_file(sf)

    async def _index_file(self, f: ScannedFile, *, force: bool = False) -> int:
        source = str(f.path)
        text = read_utf8_text_replace(f.path)
        chunks = chunk_markdown(
            text,
            source=source,
            max_chunk_size=self._max_chunk_size,
            overlap_lines=self._overlap_lines,
        )
        model = self._embedder.model_name

        # Compute composite chunk IDs (matching OpenClaw format)
        chunk_ids = {compute_chunk_id(c.source, c.start_line, c.end_line, c.content_hash, model) for c in chunks}
        old_ids = self._store.hashes_by_source(source)

        # Delete stale chunks that are no longer in the file
        stale = old_ids - chunk_ids
        if stale:
            self._store.delete_by_hashes(list(stale))

        if not chunks:
            return 0

        if not force:
            # Only embed chunks whose ID doesn't already exist
            chunks = [
                c
                for c in chunks
                if compute_chunk_id(c.source, c.start_line, c.end_line, c.content_hash, model) not in old_ids
            ]
            if not chunks:
                return 0

        return await self._embed_and_store(chunks)

    async def _embed_and_store(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0

        model = self._embedder.model_name
        total = 0
        for batch in _chunk_batches(chunks, self._embedder.batch_size):
            # Clean content for embedding: strip HTML comments and metadata noise
            # so the embedding vector captures semantics, not UUIDs/paths.
            # The original content is preserved in the Milvus record below.
            contents = [clean_content_for_embedding(c.content) for c in batch]
            embeddings = await self._embedder.embed(contents)
            total += self._store.upsert(_records_for_chunks(batch, embeddings, model))

        return total

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        source_prefix: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across indexed chunks.

        Parameters
        ----------
        query:
            Natural-language query.
        top_k:
            Maximum results to return.
        source_prefix:
            Optional path prefix to scope results. Only chunks whose
            ``source`` starts with this prefix are returned.

        Returns
        -------
        list[dict]
            Each dict contains ``content``, ``source``, ``heading``,
            ``score``, and other metadata.
        """
        filter_expr = ""
        if source_prefix is not None:
            prefix = str(Path(source_prefix).expanduser().resolve())
            escaped = prefix.replace("\\", "\\\\").replace('"', '\\"')
            filter_expr = f'source like "{escaped}%"'

        embeddings = await self._embedder.embed([query])
        fetch_k = top_k * 3 if self._reranker_model else top_k
        results = self._store.search(embeddings[0], query_text=query, top_k=fetch_k, filter_expr=filter_expr)
        if self._reranker_model and results:
            from .reranker import rerank

            results = rerank(query, results, model_name=self._reranker_model, top_k=top_k)
        return results

    # ------------------------------------------------------------------
    # Compact (compress memories)
    # ------------------------------------------------------------------

    async def compact(
        self,
        *,
        source: str | None = None,
        llm_provider: str = "openai",
        llm_model: str | None = None,
        prompt_template: str | None = None,
        output_dir: str | Path | None = None,
        llm_base_url: str | None = None,
        llm_api_key: str | None = None,
    ) -> str:
        """Compress indexed chunks into a summary and append to a daily log.

        The summary is appended to ``memory/YYYY-MM-DD.md`` inside the
        output directory (defaults to the first configured path).  The
        next ``index()`` or ``watch`` cycle will pick it up as a normal
        markdown file — keeping markdown as the single source of truth.

        Parameters
        ----------
        source:
            If given, only compact chunks from this source file.
        llm_provider:
            LLM backend for summarization.
        llm_model:
            Override the default model.
        prompt_template:
            Custom prompt template for the LLM.  Must contain a
            ``{chunks}`` placeholder.  Defaults to the built-in prompt.
        output_dir:
            Directory to write the compact file into.  Defaults to the
            first entry in *paths*.
        llm_base_url:
            Custom base URL for OpenAI-compatible API endpoints.  Only
            used when *llm_provider* is ``"openai"``.
        llm_api_key:
            API key for the LLM provider.  Only used when *llm_provider*
            is ``"openai"``.

        Returns
        -------
        str
            The generated summary markdown.
        """
        from .store import _escape_filter_value

        filter_expr = f'source == "{_escape_filter_value(source)}"' if source else ""
        all_chunks = self._store.query(filter_expr=filter_expr)
        if not all_chunks:
            return ""

        summary = await compact_chunks(
            all_chunks,
            llm_provider=llm_provider,
            model=llm_model,
            prompt_template=prompt_template,
            base_url=llm_base_url,
            api_key=llm_api_key,
        )

        # Write summary to memory/YYYY-MM-DD.md (append)
        base = Path(output_dir) if output_dir else Path(self._paths[0]) if self._paths else Path.cwd()
        memory_dir = base / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        compact_file = memory_dir / f"{date.today()}.md"
        compact_heading = "\n\n## Memory Compact\n\n"
        with open(compact_file, "a", encoding="utf-8") as f:
            if compact_file.stat().st_size == 0:
                f.write(f"# {date.today()}\n")
            f.write(compact_heading)
            f.write(summary)
            f.write("\n")

        # Index the updated file immediately
        n = await self.index_file(compact_file)
        logger.info("Compacted %d chunks into %s (%d new chunks indexed)", len(all_chunks), compact_file, n)
        return summary

    # ------------------------------------------------------------------
    # Watch
    # ------------------------------------------------------------------

    def watch(
        self,
        *,
        on_event: Callable[[str, str, Path], None] | None = None,
        on_error: Callable[[str, BaseException, Path], None] | None = None,
        debounce_ms: int | None = None,
    ) -> FileWatcher:
        """Watch configured paths for markdown changes and auto-index.

        Starts a background thread that monitors the filesystem.  When a
        markdown file is created or modified it is re-indexed automatically;
        when deleted its chunks are removed from the store.

        Parameters
        ----------
        on_event:
            Optional callback invoked *after* each event is processed.
            Signature: ``(event_type, action_summary, file_path)``.
            ``event_type`` is ``"created"``, ``"modified"``, or ``"deleted"``.
        on_error:
            Optional callback invoked after an event fails. The watcher keeps
            running after the callback.

        Returns
        -------
        FileWatcher
            The running watcher.  Call ``watcher.stop()`` when done, or
            use it as a context manager.

        Example
        -------
        ::

            mem = MemSearch(paths=["./docs/"])
            watcher = mem.watch()
            # ... watcher auto-indexes in background ...
            watcher.stop()
        """
        from .watcher import FileWatcher

        # Persistent event loop for watcher callbacks.
        #
        # asyncio.run() creates and closes a new loop on every call. Async
        # HTTP clients (httpx — used by ollama, openai, voyage) cache
        # connections tied to that loop, so a second asyncio.run() hits the
        # closed loop and raises RuntimeError: Event loop is closed.
        # This is a known httpx limitation:
        #   https://github.com/encode/httpx/discussions/2489
        #   https://github.com/encode/httpx/discussions/2959
        loop = asyncio.new_event_loop()

        def _on_change(event_type: str, file_path: Path) -> None:
            try:
                if event_type == "deleted":
                    self._store.delete_by_source(str(file_path))
                    summary = f"Removed chunks for {file_path}"
                else:
                    n = loop.run_until_complete(self.index_file(file_path))
                    summary = f"Indexed {n} chunks from {file_path}"
                logger.info(summary)
                if on_event is not None:
                    on_event(event_type, summary, file_path)
            except Exception as exc:
                # Watch is a long-running daemon callback — swallow any failure
                # (network blips, provider 500s, malformed embeddings, disk
                # errors, etc.) so a single bad file cannot crash the watcher.
                logger.exception("Failed to process %s event for %s", event_type, file_path)
                if on_error is not None:
                    on_error(event_type, exc, file_path)

        fw_kwargs: dict[str, Any] = {}
        if debounce_ms is not None:
            fw_kwargs["debounce_ms"] = debounce_ms
        watcher = FileWatcher(
            self._paths,
            _on_change,
            path_filter=lambda path: should_index_path(
                path,
                self._paths,
                ignore_files=self._ignore_files,
                exclude=self._exclude,
            ),
            **fw_kwargs,
        )
        watcher.start()
        return watcher

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def store(self) -> MilvusStore:
        return self._store

    def close(self) -> None:
        """Release resources."""
        self._store.close()

    def __enter__(self) -> MemSearch:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _chunk_batches(chunks: list[Chunk], batch_size: int) -> Iterator[list[Chunk]]:
    if batch_size <= 0:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    for i in range(0, len(chunks), batch_size):
        yield chunks[i : i + batch_size]


def _cleanup_roots_for_paths(paths: list[str | Path]) -> list[Path]:
    roots: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            roots.append(path)
    return roots


def _source_under_any_root(source: str, roots: list[Path]) -> bool:
    source_path = Path(source).expanduser().resolve()
    for root in roots:
        try:
            source_path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def _records_for_chunks(chunks: list[Chunk], embeddings: list[list[float]], model: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        chunk_id = compute_chunk_id(
            chunk.source,
            chunk.start_line,
            chunk.end_line,
            chunk.content_hash,
            model,
        )
        records.append(
            {
                "chunk_hash": chunk_id,
                "embedding": embedding,
                "content": chunk.content,
                "source": chunk.source,
                "heading": chunk.heading,
                "heading_level": chunk.heading_level,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
            }
        )
    return records
