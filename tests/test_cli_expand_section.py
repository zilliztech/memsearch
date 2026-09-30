from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from memsearch import cli as cli_module
from memsearch import store as store_module
from memsearch.chunker import chunk_markdown
from memsearch.cli import _extract_section, cli
from memsearch.config import MemSearchConfig

DAILY_LOG = (
    "## Session 10:00\n"
    "\n"
    "### 10:01\n"
    "<!-- session:AAA turn:t1 transcript:/tmp/a.jsonl -->\n"
    "- Fixed the login redirect bug.\n"
    "\n"
    "### 10:05\n"
    "<!-- session:AAA turn:t2 transcript:/tmp/a.jsonl -->\n"
    "- Added rate limiting to the API.\n"
)


def test_extract_section_starts_at_chunk_heading() -> None:
    lines = DAILY_LOG.splitlines()

    content, start, end = _extract_section(lines, 7, 3)

    assert (start, end) == (7, 9)
    assert content.startswith("### 10:05")
    assert "turn:t1" not in content


def test_extract_section_mid_section_chunk_walks_back_to_heading() -> None:
    lines = ["## A", "", "first paragraph", "", "second paragraph", "## B", "other"]

    content, start, end = _extract_section(lines, 5, 2)

    assert (start, end) == (1, 5)
    assert content.startswith("## A")


def test_expand_returns_the_chunks_own_section_and_anchor(monkeypatch, tmp_path) -> None:
    source = tmp_path / "2026-09-24.md"
    source.write_text(DAILY_LOG, encoding="utf-8")
    chunk = next(c for c in chunk_markdown(DAILY_LOG, str(source)) if c.heading == "10:05")

    class FakeStore:
        def __init__(self, **_kwargs):
            pass

        def query(self, filter_expr: str):
            return [
                {
                    "source": str(source),
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "heading": chunk.heading,
                    "heading_level": chunk.heading_level,
                }
            ]

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(store_module, "MilvusStore", FakeStore)

    result = CliRunner().invoke(cli, ["expand", "abc123", "--json-output"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["start_line"] == 7
    assert data["content"].startswith("### 10:05")
    assert data["anchor"]["turn"] == "t2"


def test_extract_section_ignores_hash_prefixed_non_heading_lines() -> None:
    para = "Deployment notes for the staging cluster and the rollback steps we agreed on. " * 3
    text = "\n".join(["## Notes", "", para.strip(), "", "#followup " + para.strip(), "", "## Next", "other"])
    chunk = next(
        c
        for c in chunk_markdown(text, "notes.md", max_chunk_size=400, overlap_lines=0)
        if c.content.startswith("#followup")
    )

    content, start, end = _extract_section(text.splitlines(), chunk.start_line, chunk.heading_level)

    assert (start, end) == (1, 6)
    assert content.startswith("## Notes")


def test_extract_section_does_not_end_at_hash_prefixed_non_heading_line() -> None:
    lines = ["## A", "text", "#tag not a heading", "more", "## B", "other"]

    content, start, end = _extract_section(lines, 1, 2)

    assert (start, end) == (1, 4)
    assert content.endswith("more")


def test_extract_section_tolerates_start_line_past_end_of_file() -> None:
    content, start, end = _extract_section(["## A", "text"], 3, 2)

    assert (start, end) == (1, 2)
    assert content == "## A\ntext"


def test_extract_section_ends_at_shallower_parent_level_heading() -> None:
    lines = ["# Root", "root intro", "## Child", "### Grandchild", "grandchild line", "## Sibling"]

    content, start, end = _extract_section(lines, start_line=4, heading_level=3)

    assert (start, end) == (4, 5)
    assert content == "### Grandchild\ngrandchild line"


@pytest.mark.parametrize("extra_args", [[], ["--lines", "2"]], ids=["section", "lines"])
@pytest.mark.parametrize(("start_line", "warns"), [(9, False), (10, True)], ids=["last-line", "past-end"])
def test_expand_warns_only_when_chunk_start_line_is_past_end_of_file(
    monkeypatch, tmp_path, start_line, warns, extra_args
) -> None:
    # DAILY_LOG has 9 lines: start_line 9 is the last line, 10 is the first past EOF.
    source = tmp_path / "2026-09-24.md"
    source.write_text(DAILY_LOG, encoding="utf-8")

    class FakeStore:
        def __init__(self, **_kwargs):
            pass

        def query(self, filter_expr: str):
            return [
                {
                    "source": str(source),
                    "start_line": start_line,
                    "end_line": start_line + 2,
                    "heading": "10:05",
                    "heading_level": 3,
                }
            ]

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "resolve_config", lambda _overrides=None: MemSearchConfig())
    monkeypatch.setattr(store_module, "MilvusStore", FakeStore)

    result = CliRunner().invoke(cli, ["expand", "abc123", "--json-output", *extra_args])

    assert result.exit_code == 0, result.output
    assert ("past the end" in result.stderr) is warns
    if warns:
        assert f"start_line {start_line}" in result.stderr
        assert f"{source} (9 lines)" in result.stderr
        assert "Re-run 'memsearch index <path>'" in result.stderr
    assert json.loads(result.stdout)["source"] == str(source)
