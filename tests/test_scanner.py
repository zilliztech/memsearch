"""Tests for the file scanner."""

from pathlib import Path

from memsearch.scanner import _maybe_add, scan_paths


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


def test_scan_empty_paths():
    results = scan_paths([])
    assert results == []


def test_scan_nonexistent_path(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    results = scan_paths([nonexistent])
    assert results == []


def test_scan_respects_custom_extensions(tmp_path: Path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.txt").write_text("# B")
    (tmp_path / "c.mkd").write_text("# C")

    results = scan_paths([tmp_path], extensions=(".txt", ".mkd"))
    paths = {r.path.name for r in results}
    assert "b.txt" in paths
    assert "c.mkd" in paths
    assert "a.md" not in paths


def test_scan_includes_hidden_when_configured(tmp_path: Path):
    (tmp_path / ".hidden.md").write_text("# hidden")
    (tmp_path / "visible.md").write_text("# visible")

    results = scan_paths([tmp_path], ignore_hidden=False)
    paths = {r.path.name for r in results}
    assert ".hidden.md" in paths
    assert "visible.md" in paths


def test_scanned_file_has_mtime_and_size(tmp_path: Path):
    f = tmp_path / "test.md"
    f.write_text("# Test content")
    results = scan_paths([f])
    assert len(results) == 1
    assert results[0].mtime > 0
    assert results[0].size == len("# Test content")


def test_maybe_add_skips_duplicate_extensions(tmp_path: Path):
    from memsearch.scanner import ScannedFile

    seen: set[str] = set()
    results: list[ScannedFile] = []
    f = tmp_path / "test.md"
    f.write_text("# Test")

    _maybe_add(f, (".md",), seen, results)
    assert len(results) == 1
    assert results[0].path.name == "test.md"

    _maybe_add(f, (".md",), seen, results)  # duplicate should be skipped
    assert len(results) == 1  # still 1, deduplication works
