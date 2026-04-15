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


def test_large_section_flushes_rolled_back_tail_line() -> None:
    """The final rolled-back line should still be emitted after the loop."""
    md = "# Big Section\n\n" + "\n".join(
        [
            "alpha " * 18,
            "beta " * 18,
            "tail " * 18,
        ]
    )

    chunks = chunk_markdown(md, source="test.md", max_chunk_size=120, overlap_lines=0)

    assert len(chunks) >= 2
    assert any("tail" in c.content for c in chunks)
    assert chunks[-1].end_line >= chunks[-1].start_line


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


def test_long_cjk_text_splits_on_cjk_sentence_boundaries() -> None:
    """Long Chinese text should prefer sentence-ending punctuation when split."""
    sentence = "这是一个用于测试中文分句行为的长句子。"
    text = sentence * 8

    chunks = chunk_markdown(text, source="zh.md", max_chunk_size=40)

    assert len(chunks) > 1
    assert all(chunk.content.endswith("。") for chunk in chunks[:-1])
    assert all(len(chunk.content) <= 40 for chunk in chunks)


def test_long_cjk_text_splits_on_question_and_exclamation_marks() -> None:
    """Chinese question/exclamation punctuation should also act as boundaries."""
    sentence = "这个问题应该怎么处理？这个方案真的可行！"
    text = sentence * 6

    chunks = chunk_markdown(text, source="zh-punct.md", max_chunk_size=30)

    assert len(chunks) > 1
    assert all(chunk.content.endswith(("？", "！")) for chunk in chunks[:-1])
    assert all(len(chunk.content) <= 30 for chunk in chunks)


def test_long_cjk_text_without_punctuation_hard_splits() -> None:
    """Long CJK text without sentence punctuation should still split safely."""
    text = "中文连续文本" * 20

    chunks = chunk_markdown(text, source="zh-no-punct.md", max_chunk_size=25)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 25 for chunk in chunks)
    assert "".join(chunk.content for chunk in chunks) == text


def test_long_mixed_cjk_and_english_text_prefers_sentence_boundaries() -> None:
    """Mixed Chinese/English text should still split on sentence punctuation."""
    sentence = "请检查 Redis cache 是否命中。Then verify the fallback path works!"
    text = sentence * 5

    chunks = chunk_markdown(text, source="mixed.md", max_chunk_size=45)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 45 for chunk in chunks)
    assert all(chunk.content.endswith(("。", "!")) for chunk in chunks[:-1])


def test_long_cjk_text_splits_on_ellipsis_boundaries() -> None:
    """Chinese ellipsis should act as a sentence boundary when splitting."""
    sentence = "这个排查过程还没结束……但是系统已经记录了关键上下文……"
    text = sentence * 4

    chunks = chunk_markdown(text, source="ellipsis.md", max_chunk_size=35)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 35 for chunk in chunks)
    assert all(chunk.content.endswith(("……",)) for chunk in chunks[:-1])


def test_cjk_wave_dash_does_not_act_as_sentence_boundary() -> None:
    """Fullwidth wave dash should fall back to hard splitting, not sentence splitting."""
    text = ("这个步骤还没结束～～继续观察系统状态～～" * 5)

    chunks = chunk_markdown(text, source="wave.md", max_chunk_size=24)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 24 for chunk in chunks)
    assert not all(chunk.content.endswith("～") for chunk in chunks[:-1])


def test_long_cjk_text_splits_on_semicolon_boundaries() -> None:
    """Chinese semicolons should act as sentence boundaries for long text."""
    sentence = "先检查缓存命中率；再确认索引是否完成；"
    text = sentence * 5

    chunks = chunk_markdown(text, source="semicolon.md", max_chunk_size=24)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 24 for chunk in chunks)
    assert all(chunk.content.endswith("；") for chunk in chunks[:-1])


def test_long_mixed_text_splits_on_ascii_semicolons() -> None:
    """ASCII semicolons should also split mixed CJK/English long text."""
    sentence = "先检查缓存; verify build;"
    text = sentence * 6

    chunks = chunk_markdown(text, source="mixed-semicolon.md", max_chunk_size=24)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 24 for chunk in chunks)
    assert all(chunk.content.endswith(";") for chunk in chunks[:-1])


def test_cjk_colon_does_not_act_as_sentence_boundary() -> None:
    """Fullwidth colons should not be treated as sentence boundaries."""
    text = ("处理步骤如下：继续检查日志输出：继续确认索引状态：" * 4)

    chunks = chunk_markdown(text, source="colon.md", max_chunk_size=22)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 22 for chunk in chunks)
    assert not all(chunk.content.endswith("：") for chunk in chunks[:-1])


def test_cjk_enumeration_comma_does_not_act_as_sentence_boundary() -> None:
    """Chinese enumeration commas should not be treated as sentence boundaries."""
    text = ("先检查缓存、再检查索引、最后检查日志、" * 5)

    chunks = chunk_markdown(text, source="enumeration.md", max_chunk_size=20)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 20 for chunk in chunks)
    assert not all(chunk.content.endswith("、") for chunk in chunks[:-1])


def test_cjk_parentheses_do_not_act_as_sentence_boundaries() -> None:
    """Fullwidth parentheses should not be treated as sentence boundaries."""
    text = ("请检查缓存命中（重点关注热数据）再检查索引状态（确认已完成）" * 4)

    chunks = chunk_markdown(text, source="parentheses.md", max_chunk_size=26)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 26 for chunk in chunks)
    assert not all(chunk.content.endswith(("（", "）")) for chunk in chunks[:-1])


def test_cjk_quotes_do_not_act_as_sentence_boundaries() -> None:
    """Chinese quotes should not be treated as sentence boundaries."""
    text = ("请检查“缓存命中率”是否正常再确认“索引状态”是否完成" * 4)

    chunks = chunk_markdown(text, source="quotes.md", max_chunk_size=24)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 24 for chunk in chunks)
    assert not all(chunk.content.endswith(("“", "”")) for chunk in chunks[:-1])


def test_mixed_path_slashes_do_not_act_as_sentence_boundaries() -> None:
    """Path-style slashes should not be treated as sentence boundaries."""
    text = ("请检查 /var/log/app 和 docs/setup/path 再确认输出是否正常" * 4)

    chunks = chunk_markdown(text, source="slashes.md", max_chunk_size=28)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 28 for chunk in chunks)
    assert not all(chunk.content.endswith("/") for chunk in chunks[:-1])


def test_mixed_underscores_do_not_act_as_sentence_boundaries() -> None:
    """Underscores in identifiers should not be treated as sentence boundaries."""
    text = ("请检查 cache_hit_rate 和 build_status_done 这两个字段是否正常" * 4)

    chunks = chunk_markdown(text, source="underscores.md", max_chunk_size=30)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 30 for chunk in chunks)
    assert not all(chunk.content.endswith("_") for chunk in chunks[:-1])


def test_mixed_hyphens_do_not_act_as_sentence_boundaries() -> None:
    """Hyphens in flags/slugs should not be treated as sentence boundaries."""
    text = ("请检查 --cache-hit-rate 和 build-status-done 这两个字段是否正常" * 4)

    chunks = chunk_markdown(text, source="hyphens.md", max_chunk_size=30)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 30 for chunk in chunks)
    assert not all(chunk.content.endswith("-") for chunk in chunks[:-1])
