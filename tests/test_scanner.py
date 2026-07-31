"""Tests for the file scanner."""

from pathlib import Path

import pytest

from memsearch.scanner import scan_paths, should_index_path


def test_scan_finds_markdown_files(tmp_path: Path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.markdown").write_text("# B")
    (tmp_path / "c.txt").write_text("not markdown")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.md").write_text("# D")

    results = scan_paths([tmp_path])
    paths = {r.path.name for r in results}
    assert "a.md" in paths
    assert "b.markdown" in paths
    assert "d.md" in paths
    assert "c.txt" not in paths


def test_scan_ignores_hidden(tmp_path: Path):
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "secret.md").write_text("# secret")
    (tmp_path / ".dotfile.md").write_text("# dot")
    (tmp_path / "visible.md").write_text("# visible")

    results = scan_paths([tmp_path], ignore_hidden=True)
    paths = {r.path.name for r in results}
    assert "visible.md" in paths
    assert "secret.md" not in paths
    assert ".dotfile.md" not in paths


def test_scan_includes_hidden_when_not_ignored(tmp_path: Path):
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "secret.md").write_text("# secret")
    (tmp_path / ".dotfile.md").write_text("# dot")

    results = scan_paths([tmp_path], ignore_hidden=False)
    paths = {r.path.name for r in results}

    assert "secret.md" in paths
    assert ".dotfile.md" in paths


def test_scan_single_file(tmp_path: Path):
    f = tmp_path / "single.md"
    f.write_text("# Single")
    results = scan_paths([f])
    assert len(results) == 1
    assert results[0].path.name == "single.md"


def test_scan_deduplicates(tmp_path: Path):
    f = tmp_path / "dup.md"
    f.write_text("# Dup")
    results = scan_paths([f, f, tmp_path])
    names = [r.path.name for r in results]
    assert names.count("dup.md") == 1


def test_ignore_support_is_disabled_by_default(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.md\n")
    ignored = tmp_path / "ignored.md"
    ignored.write_text("# Still indexed")

    results = scan_paths([tmp_path])

    assert [result.path for result in results] == [ignored]


def test_scan_applies_gitignore_rules_when_explicitly_enabled(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.md\n")
    ignored = tmp_path / "ignored.md"
    included = tmp_path / "included.md"
    ignored.write_text("# Ignored")
    included.write_text("# Included")

    results = scan_paths([tmp_path], ignore_files=[".gitignore"])

    assert [result.path for result in results] == [included]


def test_scan_never_discovers_ignore_files_from_parent_directory(tmp_path: Path):
    memory = tmp_path / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    note = memory / "note.md"
    note.write_text("# Note")
    (tmp_path / ".gitignore").write_text(".memsearch/memory/note.md\n")

    results = scan_paths([memory], ignore_files=[".gitignore"])

    assert [result.path for result in results] == [note]


def test_scan_applies_nested_ignore_files_and_negation(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / ".gitignore").write_text("*.draft.md\n")
    (docs / ".gitignore").write_text("private.md\n!keep.draft.md\n")
    public = docs / "public.md"
    private = docs / "private.md"
    kept = docs / "keep.draft.md"
    public.write_text("# Public")
    private.write_text("# Private")
    kept.write_text("# Kept")

    results = scan_paths([tmp_path], ignore_files=[".gitignore"])

    assert {result.path for result in results} == {public, kept}


def test_scan_combines_ignore_files_then_explicit_excludes(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("from-git.md\n")
    (tmp_path / ".cursorignore").write_text("from-cursor.md\n!from-git.md\n")
    from_git = tmp_path / "from-git.md"
    from_cursor = tmp_path / "from-cursor.md"
    final_exclude = tmp_path / "final.md"
    from_git.write_text("# Git")
    from_cursor.write_text("# Cursor")
    final_exclude.write_text("# Final")

    results = scan_paths(
        [tmp_path],
        ignore_files=[".gitignore", ".cursorignore"],
        exclude=["final.md"],
    )

    assert [result.path for result in results] == [from_git]


def test_explicit_file_path_bypasses_ignore_rules(tmp_path: Path):
    ignored = tmp_path / "ignored.md"
    ignored.write_text("# Explicit")
    (tmp_path / ".gitignore").write_text("ignored.md\n")

    results = scan_paths([ignored], ignore_files=[".gitignore"])

    assert [result.path for result in results] == [ignored]


def test_should_index_path_matches_directory_scan_behavior(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored/\n")
    ignored = tmp_path / "ignored" / "note.md"
    included = tmp_path / "included.md"
    hidden = tmp_path / ".hidden" / "note.md"
    ignored.parent.mkdir()
    hidden.parent.mkdir()
    ignored.write_text("# Ignored")
    included.write_text("# Included")
    hidden.write_text("# Hidden")

    assert not should_index_path(ignored, [tmp_path], ignore_files=[".gitignore"])
    assert should_index_path(included, [tmp_path], ignore_files=[".gitignore"])
    assert not should_index_path(hidden, [tmp_path], ignore_files=[".gitignore"])


def test_ignore_file_names_cannot_escape_index_root(tmp_path: Path):
    with pytest.raises(ValueError, match="without directory components"):
        scan_paths([tmp_path], ignore_files=["../.gitignore"])
