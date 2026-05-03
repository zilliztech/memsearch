"""MemSearch — main orchestrator class."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .watcher import FileWatcher

from .chunker import Chunk, chunk_markdown, clean_content_for_embedding, compute_chunk_id
from .compact import compact_chunks
from .embeddings import EmbeddingProvider, get_provider
from .scanner import ScannedFile, scan_paths
from .store import MilvusStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Scope:
    """One memory scope. See spec for full semantics.

    A scope with empty ``paths`` is read-only (search-only, never indexed).
    ``quota=None`` means "share remaining slots with other unquota'd scopes".
    ``uri``/``token`` of ``None`` means inherit from the parent ``MemSearch``.
    """

    name: str
    collection: str
    paths: list[str] = field(default_factory=list)
    quota: int | None = None
    uri: str | None = None
    token: str | None = None


def _blend_scope_results(
    per_scope: list[tuple[str, list[dict]]],
    scope_quotas: dict[str, int | None],
    default_scope_name: str,
    scope_order: list[str],
    top_k: int,
) -> list[dict]:
    """Dedup, apply per-scope quotas, return top-K blended.

    Algorithm:
      1. Tag each hit with its scope name.
      2. Dedup by chunk_hash; keep highest-scoring; remember winning scope.
      3. Quota modes:
         - all scopes have quotas → hard cap per scope, no redistribution
         - no scopes have quotas → return globally top-K by score
         - mixed → quota'd capped first; unquota'd share remainder by score
      4. Tie-break: default scope wins, then ``scope_order`` index.
    """
    # 1+2. Tag & dedup
    seen: dict[str, dict] = {}
    for scope_name, hits in per_scope:
        for h in hits:
            key = h["chunk_hash"]
            tagged = {**h, "scope": scope_name}
            existing = seen.get(key)
            if existing is None or tagged["score"] > existing["score"]:
                seen[key] = tagged

    scope_rank = {name: i for i, name in enumerate(scope_order)}

    def sort_key(r: dict) -> tuple:
        # Higher score first; then default scope wins; then config order
        return (
            -r["score"],
            0 if r["scope"] == default_scope_name else 1,
            scope_rank.get(r["scope"], len(scope_order)),
        )

    all_hits = sorted(seen.values(), key=sort_key)

    # 3. Quota modes
    quotas_present = [v for v in scope_quotas.values() if v is not None]

    # All-no-quota: just top-k
    if not quotas_present:
        return all_hits[:top_k]

    capped: dict[str, list[dict]] = {n: [] for n in scope_quotas}
    leftovers: list[dict] = []

    for h in all_hits:
        sc = h["scope"]
        q = scope_quotas.get(sc)
        if q is None:
            leftovers.append(h)
        elif len(capped[sc]) < q:
            capped[sc].append(h)
        # else: quota'd scope full; drop this hit (no redistribution)

    quota_total = sum(scope_quotas[n] or 0 for n in scope_quotas)
    remaining_slots = max(0, top_k - quota_total)
    chosen_leftovers = leftovers[:remaining_slots]

    merged = [h for hits in capped.values() for h in hits] + chosen_leftovers
    merged.sort(key=sort_key)
    return merged[:top_k]


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
        embedding_batch_size: int = 0,
        embedding_base_url: str | None = None,
        embedding_api_key: str | None = None,
        milvus_uri: str = "~/.memsearch/milvus.db",
        milvus_token: str | None = None,
        collection: str = "memsearch_chunks",
        description: str = "",
        max_chunk_size: int = 1500,
        overlap_lines: int = 2,
        reranker_model: str = "",
        default_scope_name: str = "project",
        default_scope_quota: int | None = None,
        extra_scopes: list[Scope] | None = None,
    ) -> None:
        self._paths = [str(p) for p in (paths or [])]
        self._max_chunk_size = max_chunk_size
        self._overlap_lines = overlap_lines
        self._embedder: EmbeddingProvider = get_provider(
            embedding_provider,
            model=embedding_model,
            batch_size=embedding_batch_size,
            base_url=embedding_base_url,
            api_key=embedding_api_key,
        )
        self._reranker_model = reranker_model
        self._default_scope_name = default_scope_name
        self._default_scope_quota = default_scope_quota
        self._extra_scopes: list[Scope] = list(extra_scopes or [])

        # Default scope's store (uses parent milvus_uri/token + collection kwarg)
        self._stores: dict[str, MilvusStore] = {
            default_scope_name: MilvusStore(
                uri=milvus_uri,
                token=milvus_token,
                collection=collection,
                dimension=self._embedder.dimension,
                description=description,
            )
        }
        # Back-compat alias for code that still references self._store
        self._store = self._stores[default_scope_name]

        # Extra scopes: each gets its own store, optionally on a different Milvus
        for sc in self._extra_scopes:
            if sc.name in self._stores:
                raise ValueError(f"Duplicate scope name: {sc.name!r}")
            self._stores[sc.name] = MilvusStore(
                uri=sc.uri or milvus_uri,
                token=sc.token if sc.token is not None else milvus_token,
                collection=sc.collection,
                dimension=self._embedder.dimension,
                description=description,
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
        failed = 0
        active_sources: set[str] = set()
        for f in files:
            active_sources.add(str(f.path))
            try:
                n = await self._index_file(f, force=force)
                total += n
            except Exception:
                failed += 1
                logger.exception("Failed to index %s, skipping", f.path)

        # Clean up chunks for files that no longer exist
        indexed_sources = self._store.indexed_sources()
        for source in indexed_sources:
            if source not in active_sources:
                self._store.delete_by_source(source)
                logger.info("Removed stale chunks for deleted file: %s", source)

        if failed:
            logger.warning("Indexed %d chunks from %d files (%d files failed)", total, len(files) - failed, failed)
        else:
            logger.info("Indexed %d chunks from %d files", total, len(files))
        return total

    async def index_file(self, path: str | Path) -> int:
        """Index a single file.  Returns number of chunks."""
        p = Path(path).expanduser().resolve()
        _st = p.stat()
        sf = ScannedFile(path=p, mtime=_st.st_mtime, size=_st.st_size)
        return await self._index_file(sf)

    async def _index_file(self, f: ScannedFile, *, force: bool = False) -> int:
        source = str(f.path)
        text = f.path.read_text(encoding="utf-8")
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
        # Clean content for embedding: strip HTML comments and metadata noise
        # so the embedding vector captures semantics, not UUIDs/paths.
        # The original content is preserved in the Milvus record below.
        contents = [clean_content_for_embedding(c.content) for c in chunks]
        embeddings = await self._embedder.embed(contents)

        records: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
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
        source_prefix: str | Path | None = None,
        only_scope: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across one or more scopes.

        Parameters
        ----------
        query:
            Natural-language query.
        top_k:
            Maximum results to return.
        source_prefix:
            Optional path prefix to scope results. Only chunks whose
            ``source`` starts with this prefix are returned.
            In multi-scope mode this filter applies only to the default scope.
        only_scope:
            If given, restrict the search to the named scope(s).  Raises
            ``ValueError`` if any name is not a known scope.

        Returns
        -------
        list[dict]
            Each dict contains ``content``, ``source``, ``heading``,
            ``score``, and other metadata.  In multi-scope mode each result
            also carries a ``scope`` field.
        """
        # Single-scope fast path: no extra_scopes → original behavior, no 'scope' tag
        if not self._extra_scopes:
            filter_expr = ""
            if source_prefix is not None:
                prefix = str(Path(source_prefix).expanduser().resolve())
                escaped = prefix.replace("\\", "\\\\").replace('"', '\\"')
                filter_expr = f'source like "{escaped}%"'
            embeddings = await self._embedder.embed([query])
            fetch_k = top_k * 3 if self._reranker_model else top_k
            results = self._store.search(
                embeddings[0],
                query_text=query,
                top_k=fetch_k,
                filter_expr=filter_expr,
            )
            if self._reranker_model and results:
                from .reranker import rerank

                results = rerank(query, results, model_name=self._reranker_model, top_k=top_k)
            return results

        # Multi-scope path
        all_scope_names = list(self._stores.keys())
        if only_scope is not None:
            unknown = set(only_scope) - set(all_scope_names)
            if unknown:
                raise ValueError(f"unknown scope(s) in only_scope: {sorted(unknown)}")
            active = [n for n in all_scope_names if n in set(only_scope)]
        else:
            active = all_scope_names

        # Source-prefix filter only applies to the default scope
        default_filter = ""
        if source_prefix is not None:
            prefix = str(Path(source_prefix).expanduser().resolve())
            escaped = prefix.replace("\\", "\\\\").replace('"', '\\"')
            default_filter = f'source like "{escaped}%"'

        embeddings = await self._embedder.embed([query])
        fetch_k_per = max(top_k * 2, 10)  # over-fetch for dedup margin

        async def _fetch(scope_name: str) -> tuple[str, list[dict]]:
            store = self._stores[scope_name]
            filt = default_filter if scope_name == self._default_scope_name else ""
            hits = store.search(embeddings[0], query_text=query, top_k=fetch_k_per, filter_expr=filt)
            return scope_name, hits

        per_scope = await asyncio.gather(*[_fetch(n) for n in active])

        # Build quota map
        scope_quotas: dict[str, int | None] = {}
        for sc in self._extra_scopes:
            if sc.name in active:
                scope_quotas[sc.name] = sc.quota
        if self._default_scope_name in active:
            scope_quotas[self._default_scope_name] = self._default_scope_quota

        scope_order = [self._default_scope_name] + [s.name for s in self._extra_scopes]
        merged = _blend_scope_results(
            per_scope=list(per_scope),
            scope_quotas=scope_quotas,
            default_scope_name=self._default_scope_name,
            scope_order=scope_order,
            top_k=top_k,
        )

        if self._reranker_model and merged:
            from .reranker import rerank

            merged = rerank(query, merged, model_name=self._reranker_model, top_k=top_k)
        return merged

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
            except Exception:
                # Watch is a long-running daemon callback — swallow any failure
                # (network blips, provider 500s, malformed embeddings, disk
                # errors, etc.) so a single bad file cannot crash the watcher.
                logger.exception("Failed to process %s event for %s", event_type, file_path)

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
        stores = getattr(self, "_stores", None)
        if stores is not None:
            for store in stores.values():
                store.close()
        elif (store := getattr(self, "_store", None)) is not None:
            store.close()

    def __enter__(self) -> MemSearch:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
