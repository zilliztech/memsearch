"""MemSearch — main orchestrator class."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .watcher import FileWatcher

from .chunker import Chunk, chunk_markdown, compute_chunk_id
from .embeddings import EmbeddingProvider, get_provider
from .compact import compact_chunks
from .scanner import ScannedFile, scan_paths
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
    """

    def __init__(
        self,
        paths: list[str | Path] | None = None,
        *,
        embedding_provider: str = "openai",
        embedding_model: str | None = None,
        milvus_uri: str = "~/.memsearch/milvus.db",
        milvus_token: str | None = None,
        collection: str = "memsearch_chunks",
        max_chunk_size: int = 1500,
        overlap_lines: int = 2,
    ) -> None:
        self._paths = [str(p) for p in (paths or [])]
        self._max_chunk_size = max_chunk_size
        self._overlap_lines = overlap_lines
        self._embedder: EmbeddingProvider = get_provider(
            embedding_provider, model=embedding_model
        )
        self._store = MilvusStore(
            uri=milvus_uri, token=milvus_token, collection=collection,
            dimension=self._embedder.dimension,
        )

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index(self, *, force: bool = False) -> int:
        """Scan paths and index all markdown files.

        Returns the number of chunks indexed.  Also removes chunks for
        files that no longer exist on disk (deleted-file cleanup).
        """
        files = scan_paths(self._paths)
        total = 0
        active_sources: set[str] = set()
        for f in files:
            active_sources.add(str(f.path))
            n = await self._index_file(f, force=force)
            total += n

        # Clean up chunks for files that no longer exist
        indexed_sources = self._store.indexed_sources()
        for source in indexed_sources:
            if source not in active_sources:
                self._store.delete_by_source(source)
                logger.info("Removed stale chunks for deleted file: %s", source)

        logger.info("Indexed %d chunks from %d files", total, len(files))
        return total

    async def index_file(self, path: str | Path) -> int:
        """Index a single file.  Returns number of chunks."""
        p = Path(path).expanduser().resolve()
        sf = ScannedFile(path=p, mtime=p.stat().st_mtime, size=p.stat().st_size)
        return await self._index_file(sf)

    async def _index_file(self, f: ScannedFile, *, force: bool = False) -> int:
        source = str(f.path)
        text = f.path.read_text(encoding="utf-8")
        chunks = chunk_markdown(
            text, source=source,
            max_chunk_size=self._max_chunk_size,
            overlap_lines=self._overlap_lines,
        )
        model = self._embedder.model_name

        # Compute composite chunk IDs (matching OpenClaw format)
        chunk_ids = {
            compute_chunk_id(c.source, c.start_line, c.end_line, c.content_hash, model)
            for c in chunks
        }
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
                c for c in chunks
                if compute_chunk_id(c.source, c.start_line, c.end_line, c.content_hash, model)
                not in old_ids
            ]
            if not chunks:
                return 0

        return await self._embed_and_store(chunks)

    async def _embed_and_store(
        self, chunks: list[Chunk], *, batch_size: int = 96
    ) -> int:
        if not chunks:
            return 0

        model = self._embedder.model_name
        contents = [c.content for c in chunks]

        # Batch embedding calls to stay within provider limits (e.g. Google: 100)
        embeddings: list[list[float]] = []
        for i in range(0, len(contents), batch_size):
            batch = contents[i : i + batch_size]
            batch_embeddings = await self._embedder.embed(batch)
            embeddings.extend(batch_embeddings)

        records: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            chunk_id = compute_chunk_id(
                chunk.source, chunk.start_line, chunk.end_line,
                chunk.content_hash, model,
            )
            records.append(
                {
                    "chunk_hash": chunk_id,
                    "embedding": embeddings[i],
                    "content": chunk.content,
                    "source": chunk.source,
                    "heading": chunk.heading,
                    "heading_level": chunk.heading_level,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                }
            )

        return self._store.upsert(records)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic search across indexed chunks.

        Parameters
        ----------
        query:
            Natural-language query.
        top_k:
            Maximum results to return.

        Returns
        -------
        list[dict]
            Each dict contains ``content``, ``source``, ``heading``,
            ``score``, and other metadata.
        """
        embeddings = await self._embedder.embed([query])
        return self._store.search(embeddings[0], query_text=query, top_k=top_k)

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

        Returns
        -------
        str
            The generated summary markdown.
        """
        filter_expr = f'source == "{source}"' if source else ""
        all_chunks = self._store.query(filter_expr=filter_expr)
        if not all_chunks:
            return ""

        summary = await compact_chunks(
            all_chunks, llm_provider=llm_provider, model=llm_model,
            prompt_template=prompt_template,
        )

        # Write summary to memory/YYYY-MM-DD.md (append)
        base = Path(output_dir) if output_dir else Path(self._paths[0]) if self._paths else Path.cwd()
        memory_dir = base / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        compact_file = memory_dir / f"{date.today()}.md"
        compact_heading = f"\n\n## Memory Compact\n\n"
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

        def _on_change(event_type: str, file_path: Path) -> None:
            if event_type == "deleted":
                self._store.delete_by_source(str(file_path))
                summary = f"Removed chunks for {file_path}"
            else:
                n = asyncio.run(self.index_file(file_path))
                summary = f"Indexed {n} chunks from {file_path}"
            logger.info(summary)
            if on_event is not None:
                on_event(event_type, summary, file_path)

        fw_kwargs: dict[str, Any] = {}
        if debounce_ms is not None:
            fw_kwargs["debounce_ms"] = debounce_ms
        watcher = FileWatcher(self._paths, _on_change, **fw_kwargs)
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
