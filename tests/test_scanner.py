"""Tests for the file scanner."""

from pathlib import Path

from memsearch.scanner import scan_paths


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
