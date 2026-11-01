"""MCP (Model Context Protocol) server for memsearch.

Exposes memsearch over the Model Context Protocol so that any MCP client
(Codex, Claude Code, DeepSeek Harness, ...) can search memory, index
documents and call the configured embedding / rerank backends as tools.

Transport
---------
stdio, JSON-RPC 2.0, one JSON object per line, UTF-8.  MCP deliberately
does *not* use LSP-style ``Content-Length`` framing on stdio.

Usage
-----
::

    memsearch mcp                       # honour ~/.memsearch/config.toml
    memsearch mcp -c my_collection      # explicit collection
    memsearch mcp --knowledge-db ~/.dsh/storages/knowledge-chunks.sqlite

The server has no third-party dependencies: the protocol is implemented
with the standard library only, so it can be started by any Python 3.10+
interpreter that has memsearch importable.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .config import MemSearchConfig, memsearch_kwargs_from_config

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "memsearch"


def _package_version() -> str:
    """Return the installed memsearch version (``0.0.0`` when unknown)."""
    try:
        from importlib.metadata import version

        return version("memsearch")
    except Exception:  # pragma: no cover - source checkout without metadata
        return "0.0.0"


SERVER_VERSION = _package_version()

#: Environment variable pointing at a DeepSeek Harness knowledge store.
KNOWLEDGE_DB_ENV = "MEMSEARCH_KNOWLEDGE_DB"

#: Default store location written by the third-party ``dsh-knowledge`` plugin
#: (https://github.com/Soren-ABT/dsh-knowledge).  Not part of DeepSeek Harness
#: itself — the tool is only exposed when this file (or an explicit override)
#: exists.
DEFAULT_KNOWLEDGE_DB = Path("~/.dsh/storages/knowledge-chunks.sqlite")


def _auto_knowledge_db() -> str:
    """Return the default dsh-knowledge store path if it exists, else ``""``."""
    expanded = DEFAULT_KNOWLEDGE_DB.expanduser()
    return str(expanded) if expanded.is_file() else ""


def _reconfigure_streams() -> None:
    """Force UTF-8 on the stdio streams.

    On Windows the default encoding for pipes is the console code page
    (GBK on a zh-CN machine), which corrupts the JSON-RPC payload and the
    Chinese text it carries.  MCP is always UTF-8.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):  # pragma: no cover
            stream.reconfigure(encoding="utf-8", errors="replace")


class MCPServer:
    """Serve memsearch tools over the Model Context Protocol.

    The heavy resources (embedding provider, Milvus store) are created on
    first use, so ``initialize`` and ``tools/list`` still work when the
    embedding backend is unreachable — the client gets a proper error from
    the tool call instead of a dead server.
    """

    def __init__(
        self,
        *,
        config: MemSearchConfig,
        collection: str | None = None,
        knowledge_db: str | None = None,
        max_content_chars: int = 2000,
    ) -> None:
        self._cfg = config
        self._collection = collection or config.milvus.collection
        self._max_content_chars = max_content_chars
        self._knowledge_db = knowledge_db or os.environ.get(KNOWLEDGE_DB_ENV) or _auto_knowledge_db()
        self._ms = None
        self._store = None

    # ------------------------------------------------------------------
    # lazily created resources
    # ------------------------------------------------------------------

    def _memsearch(self):
        """Return (and cache) a MemSearch instance for the configured collection."""
        if self._ms is None:
            from .core import MemSearch

            kwargs = memsearch_kwargs_from_config(self._cfg)
            kwargs["collection"] = self._collection
            self._ms = MemSearch(**kwargs)
        return self._ms

    def _get_store(self):
        """Return (and cache) a Milvus store for read-only operations."""
        if self._store is None:
            from .store import MilvusStore

            self._store = MilvusStore(
                uri=self._cfg.milvus.uri,
                token=self._cfg.milvus.token or None,
                collection=self._collection,
                dimension=None,
            )
        return self._store

    def close(self) -> None:
        for closable in (self._ms, self._store):
            close = getattr(closable, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):  # pragma: no cover - best effort
                    close()
        self._ms = None
        self._store = None

    # ------------------------------------------------------------------
    # tool implementations
    # ------------------------------------------------------------------

    def tool_memory_search(self, args: dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        limit = int(args.get("limit") or 5)
        source_prefix = args.get("source_prefix") or None

        import asyncio

        results = asyncio.run(self._memsearch().search(query, top_k=limit, source_prefix=source_prefix))
        if not results:
            return "(no match)"

        blocks = []
        for i, r in enumerate(results, 1):
            content = (r.get("content") or "").strip()
            if len(content) > self._max_content_chars:
                content = content[: self._max_content_chars] + " ...[truncated]"
            heading = r.get("heading") or ""
            blocks.append(
                f"[{i}] score={float(r.get('score', 0.0)):.4f}  {r.get('source', '?')}  #{heading}\n"
                f"{content}\n"
                f"    (chunk_id={r.get('chunk_hash', '')}  lines "
                f"{r.get('start_line', '?')}-{r.get('end_line', '?')})"
            )
        return "\n\n".join(blocks)

    def tool_memory_index(self, args: dict[str, Any]) -> str:
        raw = args.get("paths") or args.get("path") or []
        if isinstance(raw, str):
            raw = [raw]
        paths = [str(p) for p in raw if str(p).strip()]
        if not paths:
            raise ValueError("paths is required (a markdown file or a directory)")
        missing = [p for p in paths if not Path(p).expanduser().exists()]
        if missing:
            raise ValueError(f"path not found: {', '.join(missing)}")
        force = bool(args.get("force"))

        import asyncio

        from .core import MemSearch

        kwargs = memsearch_kwargs_from_config(self._cfg)
        kwargs["collection"] = self._collection
        kwargs["paths"] = [str(Path(p).expanduser().resolve()) for p in paths]
        ms = MemSearch(**kwargs)
        try:
            count = asyncio.run(ms.index(force=force))
        finally:
            ms.close()
        return f"indexed {count} chunk(s) from {', '.join(paths)}"

    def tool_memory_stats(self, args: dict[str, Any]) -> str:
        count = self._get_store().count()
        lines = [f"collection: {self._collection}", f"Total indexed chunks: {count}"]
        try:
            sources = sorted(self._get_store().indexed_sources())
        except Exception:  # pragma: no cover - backend dependent
            sources = []
        if sources:
            lines.append(f"source files: {len(sources)}")
            lines.extend(f"  {s}" for s in sources[:20])
        return "\n".join(lines)

    def tool_memory_expand(self, args: dict[str, Any]) -> str:
        chunk_hash = str(args.get("chunk_id") or args.get("chunk_hash") or "").strip()
        if not chunk_hash:
            raise ValueError("chunk_id is required")
        lines_ctx = args.get("lines")
        chunks = self._get_store().query(filter_expr=f'chunk_hash == "{chunk_hash}"')
        if not chunks:
            return f"chunk not found: {chunk_hash}"
        chunk = chunks[0]

        from .expand import extract_section
        from .io import read_utf8_text_replace

        source = chunk.get("source", "")
        path = Path(source)
        if not path.exists():
            return f"source file not found: {source}"
        all_lines = read_utf8_text_replace(path).splitlines()
        start_line = int(chunk.get("start_line", 1))
        end_line = int(chunk.get("end_line", start_line))

        if lines_ctx is not None:
            n = int(lines_ctx)
            ctx_start = max(0, start_line - 1 - n)
            ctx_end = min(len(all_lines), end_line + n)
            expanded = "\n".join(all_lines[ctx_start:ctx_end])
            first, last = ctx_start + 1, ctx_end
        else:
            expanded, first, last = extract_section(all_lines, start_line, int(chunk.get("heading_level", 0) or 0))
        head = f"Source: {source} (lines {first}-{last})"
        if chunk.get("heading"):
            head += f"\nHeading: {chunk['heading']}"
        return f"{head}\n\n{expanded}"

    def tool_embed(self, args: dict[str, Any]) -> str:
        raw = args.get("texts")
        if isinstance(raw, str):
            raw = [raw]
        texts = [str(t) for t in (raw or [])]
        if not texts:
            raise ValueError("texts is required (string or list of strings)")

        import asyncio

        provider = self._memsearch()._embedder
        vectors = asyncio.run(provider.embed(texts))
        include = bool(args.get("include_vector"))
        payload = {
            "model": provider.model_name,
            "count": len(vectors),
            "dimension": provider.dimension,
            "vectors": [],
        }
        for vec in vectors:
            norm = sum(x * x for x in vec) ** 0.5
            item: dict[str, Any] = {"norm": round(norm, 6)}
            if include:
                item["embedding"] = vec
            payload["vectors"].append(item)
        return json.dumps(payload, ensure_ascii=False, indent=1)

    def tool_rerank(self, args: dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        raw = args.get("documents") or []
        if isinstance(raw, str):
            raw = [raw]
        documents = [str(d) for d in raw]
        if not query or not documents:
            raise ValueError("query and documents are required")

        model = self._cfg.reranker.model or ""
        if not model.startswith("remote:"):
            raise ValueError(
                "no remote reranker configured: set reranker.model to 'remote:<model>' in ~/.memsearch/config.toml"
            )
        from .remote_reranker import RemoteReranker

        reranker = RemoteReranker(model=model.split(":", 1)[1])
        candidates = [{"content": doc} for doc in documents]
        ranked = reranker.rerank(query, candidates)
        return "\n".join(f"{i}. score={r['score']:.6f}  {documents[i]}" for i, r in enumerate(ranked[: len(documents)]))

    def tool_knowledge_search(self, args: dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        if not self._knowledge_db:
            raise ValueError(
                "no knowledge store found: install the dsh-knowledge plugin "
                f"(its store at {DEFAULT_KNOWLEDGE_DB} is picked up automatically), "
                f"pass --knowledge-db, or set {KNOWLEDGE_DB_ENV}"
            )
        limit = int(args.get("limit") or 5)
        base_id = args.get("base_id") or None

        from .knowledge_store import KnowledgeStore

        store = KnowledgeStore(self._knowledge_db)
        try:
            hits = store.search(
                query,
                limit=limit,
                base_id=base_id,
                embed_fn=self._embed_texts,
                rerank_fn=self._rerank_documents,
            )
        finally:
            store.close()
        if not hits:
            return "(no match)"
        return "\n\n".join(
            f"[{i}] score={h['score']:.6f}  doc={h.get('doc_id', '')}  #{h.get('heading') or ''}\n"
            f"{h['text'][: self._max_content_chars]}"
            for i, h in enumerate(hits, 1)
        )

    # ------------------------------------------------------------------
    # helpers used by the knowledge tool
    # ------------------------------------------------------------------

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        return asyncio.run(self._memsearch()._embedder.embed(texts))

    def _rerank_documents(self, query: str, documents: list[str]) -> list[float] | None:
        model = self._cfg.reranker.model or ""
        if not model.startswith("remote:"):
            return None
        try:
            from .remote_reranker import RemoteReranker

            reranker = RemoteReranker(model=model.split(":", 1)[1])
            response = reranker.evaluate(query, documents)
            scores = reranker.scores(response, len(documents))
        except Exception:
            return None
        return [scores.get(i, 0.0) for i in range(len(documents))]

    # ------------------------------------------------------------------
    # tool registry
    # ------------------------------------------------------------------

    def tool_definitions(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = [
            {
                "name": "memory_search",
                "description": (
                    "Search memsearch's persistent memory (hybrid dense + BM25, "
                    "optionally cross-encoder reranked). Use it to recall earlier "
                    "decisions, commands, files and outcomes."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "natural language or keywords"},
                        "limit": {"type": "integer", "description": "max hits (default 5)"},
                        "source_prefix": {
                            "type": "string",
                            "description": "only chunks whose source path starts with this prefix",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memory_index",
                "description": "Index markdown files or directories into the memsearch collection.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "markdown file(s) or directory(ies)",
                        },
                        "force": {"type": "boolean", "description": "re-embed everything"},
                    },
                    "required": ["paths"],
                },
            },
            {
                "name": "memory_stats",
                "description": "Show the chunk count and indexed source files of a collection.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "memory_expand",
                "description": (
                    "Expand one memory chunk to its full heading section (progressive "
                    "disclosure step 2: search -> expand -> transcript)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {"type": "string", "description": "chunk_hash from memory_search"},
                        "lines": {"type": "integer", "description": "show N lines around the chunk"},
                    },
                    "required": ["chunk_id"],
                },
            },
            {
                "name": "embed",
                "description": (
                    "Embed text with the configured embedding provider (OpenAI-compatible endpoint by default)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "texts": {"type": "array", "items": {"type": "string"}},
                        "include_vector": {
                            "type": "boolean",
                            "description": "return the full vectors (large)",
                        },
                    },
                    "required": ["texts"],
                },
            },
            {
                "name": "rerank",
                "description": (
                    "Cross-encoder rerank documents against a query using the "
                    "configured remote reranker (reranker.model = 'remote:...')."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "documents": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["query", "documents"],
                },
            },
        ]
        if self._knowledge_db and Path(self._knowledge_db).expanduser().exists():
            tools.append(
                {
                    "name": "knowledge_search",
                    "description": (
                        "Hybrid search (dense vectors + BM25) over the knowledge store of the "
                        "third-party dsh-knowledge DSH plugin, with cross-encoder reranking."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "description": "max hits (default 5)"},
                            "base_id": {"type": "string", "description": "restrict to one base id"},
                        },
                        "required": ["query"],
                    },
                }
            )
        return tools

    def _dispatch_tool(self, name: str, args: dict[str, Any]) -> str:
        handlers = {
            "memory_search": self.tool_memory_search,
            "memory_index": self.tool_memory_index,
            "memory_stats": self.tool_memory_stats,
            "memory_expand": self.tool_memory_expand,
            "embed": self.tool_embed,
            "rerank": self.tool_rerank,
            "knowledge_search": self.tool_knowledge_search,
        }
        handler = handlers.get(name)
        if handler is None:
            raise KeyError(name)
        return handler(args)

    # ------------------------------------------------------------------
    # JSON-RPC plumbing
    # ------------------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC message; return the reply (or None for notifications)."""
        method = message.get("method")
        mid = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": (
                        "memsearch MCP: memory_search recalls past sessions, "
                        "memory_expand returns full context, embed/rerank call the "
                        "configured backends."
                    ),
                },
            }
        if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": self.tool_definitions()}}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                text = self._dispatch_tool(str(name), arguments)
                is_error = False
            except KeyError:
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": f"unknown tool: {name}"},
                }
            except Exception as exc:
                text = f"{type(exc).__name__}: {exc}"
                is_error = True
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": str(text)}],
                    "isError": is_error,
                },
            }
        if mid is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }


def serve(
    *,
    config: MemSearchConfig,
    collection: str | None = None,
    knowledge_db: str | None = None,
    max_content_chars: int = 2000,
    stdin=None,
    stdout=None,
    server: MCPServer | None = None,
) -> None:
    """Run the MCP server until stdin is closed.

    Pass *server* to reuse an already configured instance (the tests do
    that to inject fakes); otherwise one is created from *config*.
    """
    _reconfigure_streams()
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    if server is None:
        server = MCPServer(
            config=config,
            collection=collection,
            knowledge_db=knowledge_db,
            max_content_chars=max_content_chars,
        )
    try:
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                reply = server.handle(message)
            except Exception as exc:
                reply = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
                }
            if reply is not None:
                sink.write(json.dumps(reply, ensure_ascii=False) + "\n")
                sink.flush()
    finally:
        server.close()
