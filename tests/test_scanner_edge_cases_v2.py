"""Additional edge case tests for scanner module."""

from __future__ import annotations

from pathlib import Path

from memsearch.scanner import _maybe_add, scan_paths


class TestScannerEdgeCasesV2:
    def test_scan_with_empty_extensions(self, tmp_path: Path):
        """Empty extensions tuple should not match any files."""
        (tmp_path / "file.md").write_text("# Test")
        results = scan_paths([tmp_path], extensions=())
        assert results == []

    def test_scan_single_file_direct(self, tmp_path: Path):
        """Scanning a single file directly."""
        f = tmp_path / "direct.md"
        f.write_text("# Direct")
        results = scan_paths([f])
        assert len(results) == 1
        assert results[0].path.name == "direct.md"

    def test_scan_nonexistent_path(self, tmp_path: Path):
        """Non-existent path should return empty list."""
        results = scan_paths([tmp_path / "does_not_exist"])
        assert results == []

    def test_scan_directory_with_only_hidden(self, tmp_path: Path):
        """Directory with only hidden files."""
        (tmp_path / ".hidden.md").write_text("# Hidden")
        results = scan_paths([tmp_path], ignore_hidden=True)
        assert results == []

    def test_scan_with_multiple_sources(self, tmp_path: Path):
        """Scanning multiple source directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "a.md").write_text("# A")
        (dir2 / "b.md").write_text("# B")

        results = scan_paths([dir1, dir2])
        names = {r.path.name for r in results}
        assert "a.md" in names
        assert "b.md" in names

    def test_scan_result_sorting(self, tmp_path: Path):
        """Results should be sorted by path."""
        (tmp_path / "z.md").write_text("# Z")
        (tmp_path / "a.md").write_text("# A")
        (tmp_path / "m.md").write_text("# M")

        results = scan_paths([tmp_path])
        names = [r.path.name for r in results]
        assert names == sorted(names)


class TestMaybeAddEdgeCases:
    def test_maybe_add_wrong_extension(self, tmp_path: Path):
        """_maybe_add should skip non-matching extensions."""
        from memsearch.scanner import ScannedFile

        seen: set[str] = set()
        results: list[ScannedFile] = []
        f = tmp_path / "test.txt"
        f.write_text("text")

        _maybe_add(f, (".md",), seen, results)
        assert len(results) == 0

    def test_maybe_add_duplicate_prevention(self, tmp_path: Path):
        """_maybe_add should prevent duplicates via seen set."""
        from memsearch.scanner import ScannedFile

        seen: set[str] = set()
        results: list[ScannedFile] = []
        f = tmp_path / "test.md"
        f.write_text("# Test")

        _maybe_add(f, (".md",), seen, results)
        _maybe_add(f, (".md",), seen, results)  # Duplicate

        assert len(results) == 1