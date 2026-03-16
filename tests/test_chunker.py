"""Tests for the markdown chunker."""

from memsearch.chunker import chunk_markdown, compute_chunk_id


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


def test_compute_chunk_id_is_deterministic_and_model_sensitive():
    common = {
        "source": "doc.md",
        "start_line": 1,
        "end_line": 10,
        "content_hash": "abcdef1234567890",
    }
    id_a = compute_chunk_id(**common, model="text-embedding-3-small")
    id_b = compute_chunk_id(**common, model="text-embedding-3-small")
    id_c = compute_chunk_id(**common, model="text-embedding-3-large")

    assert id_a == id_b
    assert id_a != id_c
