"""Search the web into attributed markdown, then recall it with MemSearch."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from memsearch import MemSearch

MCP_URL = "https://search.parallel.ai/mcp"
USER_AGENT = "memsearch-parallel-research/0.1 (+https://github.com/zilliztech/memsearch)"


async def call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise RuntimeError(f"{name} failed: {result.content}")
    if result.structuredContent is not None:
        return result.structuredContent
    # Some MCP clients/servers expose the JSON result only as text content.
    for block in result.content:
        if block.type == "text":
            return json.loads(block.text)
    raise RuntimeError(f"{name} returned no JSON content")


async def collect_pages(query: str, fetch_urls: list[str]) -> list[dict[str, Any]]:
    # One anonymous client owns discovery, search and fetch. No environment or
    # saved credentials are loaded; the endpoint is fixed to the public server.
    async with (
        httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=60) as client,
        streamable_http_client(MCP_URL, http_client=client) as (read, write, _),
        ClientSession(read, write, read_timeout_seconds=timedelta(seconds=60)) as session,
    ):
        await session.initialize()
        tools = {tool.name for tool in (await session.list_tools()).tools}
        required = {"web_search", "web_fetch"} if fetch_urls else {"web_search"}
        if not required <= tools:
            raise RuntimeError(f"MCP server is missing tools: {sorted(required - tools)}")
        search = await call_tool(session, "web_search", {"objective": query, "search_queries": [query]})
        pages = search["results"][:3]
        if fetch_urls:
            fetched = await call_tool(session, "web_fetch", {"urls": fetch_urls, "session_id": search["session_id"]})
            if fetched.get("errors"):
                raise RuntimeError(f"Page fetching failed: {fetched['errors']}")
            pages += fetched["results"]
        if not pages:
            raise RuntimeError("No web results found; try a more specific query.")
        return pages


def save_pages(pages: list[dict[str, Any]], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for page in pages:
        content = "\n\n".join(page["excerpts"]).strip()
        if not content:
            continue
        url = page["url"]
        title = " ".join((page.get("title") or url).split())
        filename = hashlib.sha256(url.encode()).hexdigest() + ".md"
        # URL-derived names cannot escape the notes directory. Repeating a URL
        # updates its snapshot rather than creating duplicate files.
        (directory / filename).write_text(f"# {title}\n\nSource: {url}\n\n{content}\n", encoding="utf-8")


async def research(query: str, directory: Path, fetch_urls: list[str], *, recall_only: bool = False) -> None:
    directory = directory.expanduser().resolve()
    pages_dir = directory / "pages"
    if not recall_only:
        save_pages(await collect_pages(query, fetch_urls), pages_dir)
    elif not pages_dir.is_dir():
        raise RuntimeError("No saved research found in this directory. Run without --recall-only first.")

    with MemSearch(
        paths=[pages_dir],
        embedding_provider="onnx",
        milvus_uri=str(directory / "research.db"),
        collection="parallel_research",
    ) as mem:
        report = await mem.index_with_report()
        if report.failed_files:
            raise RuntimeError(f"Indexing failed: {report.failed_files}")
        results = await mem.search(query, top_k=3)
        if not results:
            raise RuntimeError("No indexed research found.")
        for result in results:
            print(f"[{result['source']}]\n{result['content']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Research topic or local recall query")
    parser.add_argument("--directory", type=Path, default=Path(".memsearch/research"))
    parser.add_argument("--fetch-url", action="append", default=[], help="Also extract excerpts from this URL")
    parser.add_argument("--recall-only", action="store_true", help="Search saved notes without contacting Parallel")
    args = parser.parse_args()
    if len(args.fetch_url) > 20:
        parser.error("--fetch-url accepts at most 20 URLs")
    if args.recall_only and args.fetch_url:
        parser.error("--fetch-url cannot be used with --recall-only")
    asyncio.run(research(args.query, args.directory, args.fetch_url, recall_only=args.recall_only))


if __name__ == "__main__":
    main()
