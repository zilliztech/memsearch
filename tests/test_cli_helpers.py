from memsearch.cli import _build_cli_overrides, _cfg_to_memsearch_kwargs, _extract_section
from memsearch.config import MemSearchConfig


def test_build_cli_overrides_skips_none_and_nests_values() -> None:
    overrides = _build_cli_overrides(
        provider="google",
        model=None,
        batch_size=64,
        collection="team-memory",
        milvus_uri="/tmp/milvus.db",
        milvus_token=None,
        llm_provider="anthropic",
        llm_model="claude-3-7-sonnet",
        max_chunk_size=2400,
        overlap_lines=4,
        debounce_ms=900,
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )

    assert overrides == {
        "embedding": {"provider": "google", "batch_size": 64},
        "milvus": {"collection": "team-memory", "uri": "/tmp/milvus.db"},
        "compact": {"llm_provider": "anthropic", "llm_model": "claude-3-7-sonnet"},
        "chunking": {"max_chunk_size": 2400, "overlap_lines": 4},
        "watch": {"debounce_ms": 900},
        "reranker": {"model": "cross-encoder/ms-marco-MiniLM-L-6-v2"},
    }


def test_cfg_to_memsearch_kwargs_normalizes_empty_optional_strings() -> None:
    cfg = MemSearchConfig()
    cfg.embedding.provider = "openai"
    cfg.embedding.model = ""
    cfg.embedding.batch_size = 128
    cfg.embedding.base_url = ""
    cfg.embedding.api_key = ""
    cfg.milvus.uri = "/tmp/memsearch.db"
    cfg.milvus.token = ""
    cfg.milvus.collection = "notes"
    cfg.chunking.max_chunk_size = 2048
    cfg.chunking.overlap_lines = 3
    cfg.reranker.model = ""

    kwargs = _cfg_to_memsearch_kwargs(cfg)

    assert kwargs == {
        "embedding_provider": "openai",
        "embedding_model": None,
        "embedding_batch_size": 128,
        "embedding_base_url": None,
        "embedding_api_key": None,
        "milvus_uri": "/tmp/memsearch.db",
        "milvus_token": None,
        "collection": "notes",
        "max_chunk_size": 2048,
        "overlap_lines": 3,
        "reranker_model": "",
    }


def test_extract_section_returns_top_level_section_until_next_peer_heading() -> None:
    lines = [
        "# Intro",
        "intro line",
        "## Details",
        "detail line",
        "### Deep dive",
        "deep detail",
        "# Next",
        "next line",
    ]

    content, start, end = _extract_section(lines, start_line=4, heading_level=2)

    assert content == "## Details\ndetail line\n### Deep dive\ndeep detail"
    assert start == 3
    assert end == 6


def test_extract_section_expands_to_parent_section_for_nested_heading_chunks() -> None:
    lines = [
        "# Root",
        "root intro",
        "## Child",
        "child line 1",
        "child line 2",
        "### Grandchild",
        "grandchild line",
        "## Sibling",
        "sibling line",
    ]

    content, start, end = _extract_section(lines, start_line=6, heading_level=3)

    assert content == "## Child\nchild line 1\nchild line 2\n### Grandchild\ngrandchild line"
    assert start == 3
    assert end == 7


def test_extract_section_returns_entire_tail_section_at_end_of_file() -> None:
    lines = [
        "# One",
        "one line",
        "# Two",
        "two line",
        "tail line",
    ]

    content, start, end = _extract_section(lines, start_line=5, heading_level=1)

    assert content == "# Two\ntwo line\ntail line"
    assert start == 3
    assert end == 5


def test_extract_section_falls_back_to_chunk_bounds_when_heading_level_is_zero() -> None:
    lines = [
        "preamble",
        "still preamble",
        "chunk body",
        "tail",
    ]

    content, start, end = _extract_section(lines, start_line=3, heading_level=0)

    assert content == "chunk body\ntail"
    assert start == 3
    assert end == 4
