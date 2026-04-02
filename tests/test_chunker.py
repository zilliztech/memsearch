"""Tests for the markdown chunker."""

from memsearch.chunker import chunk_markdown, clean_content_for_embedding


def test_simple_heading_split():
    md = """\
# Title

Some intro text.

## Section A

Content A here.

## Section B

Content B here.
"""
    chunks = chunk_markdown(md, source="test.md")
    assert len(chunks) >= 3
    headings = [c.heading for c in chunks]
    assert "Title" in headings
    assert "Section A" in headings
    assert "Section B" in headings


def test_preamble_without_heading():
    md = "Just some text without any heading.\n\nMore text."
    chunks = chunk_markdown(md, source="test.md")
    assert len(chunks) == 1
    assert chunks[0].heading == ""
    assert chunks[0].heading_level == 0


def test_empty_input():
    chunks = chunk_markdown("", source="test.md")
    assert chunks == []


def test_content_hash_is_deterministic():
    md = "# Hello\n\nWorld"
    c1 = chunk_markdown(md, source="a.md")
    c2 = chunk_markdown(md, source="b.md")
    # Same content -> same content_hash, even different source
    assert c1[0].content_hash == c2[0].content_hash


def test_large_section_splitting():
    # Create a section larger than max_chunk_size
    paragraphs = [f"Paragraph {i}. " + "x" * 200 for i in range(20)]
    md = "# Big Section\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_markdown(md, source="test.md", max_chunk_size=500)
    assert len(chunks) > 1
    for c in chunks:
        assert c.heading == "Big Section"


def test_source_and_lines():
    md = "# A\n\nline1\n\n# B\n\nline2"
    chunks = chunk_markdown(md, source="doc.md")
    assert all(c.source == "doc.md" for c in chunks)
    assert chunks[0].start_line >= 1


def test_empty_session_heading_filtered():
    """Headings with no meaningful body text should be dropped."""
    md = """\
## Session 03:16

## Session 03:17

### 03:18
<!-- session:abc-123 turn:def-456 transcript:/path/to/file.jsonl -->
- User asked about something important and Claude provided a detailed answer.
"""
    chunks = chunk_markdown(md, source="daily.md")
    # The two empty "## Session" sections should be filtered out
    assert all("Session 03:16" not in c.heading for c in chunks)
    assert all("Session 03:17" not in c.heading for c in chunks)
    # The section with real content should survive
    assert len(chunks) >= 1
    assert any("something important" in c.content for c in chunks)


def test_html_comment_only_chunk_filtered():
    """A chunk with only a heading and HTML comment should be dropped."""
    md = """\
### 08:00
<!-- session:aaa-bbb turn:ccc-ddd transcript:/tmp/foo.jsonl -->
"""
    chunks = chunk_markdown(md, source="daily.md")
    assert chunks == []


def test_clean_content_for_embedding():
    """HTML comments should be stripped for embedding but content preserved."""
    text = (
        "### 03:18\n"
        "<!-- session:abc-123 turn:def-456 transcript:/path/to/file.jsonl -->\n"
        "- User asked about chunking optimization."
    )
    cleaned = clean_content_for_embedding(text)
    assert "session:abc-123" not in cleaned
    assert "transcript:" not in cleaned
    assert "chunking optimization" in cleaned


def test_clean_content_collapses_blank_lines():
    """Removing comments should not leave excessive blank lines."""
    text = "Line one.\n\n<!-- comment -->\n\n\n\nLine two."
    cleaned = clean_content_for_embedding(text)
    assert "\n\n\n" not in cleaned
    assert "Line one." in cleaned
    assert "Line two." in cleaned


def test_clean_content_handles_adjacent_html_comments() -> None:
    """Back-to-back HTML comments should not leave comment holes behind."""
    text = "Header\n<!-- first comment -->\n<!-- second comment -->\n\nBody text"

    cleaned = clean_content_for_embedding(text)

    assert "first comment" not in cleaned
    assert "second comment" not in cleaned
    assert cleaned == "Header\n\nBody text"
