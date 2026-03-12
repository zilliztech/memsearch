"""Tests for ScannedFile data structure."""

from __future__ import annotations

from pathlib import Path

from memsearch.scanner import ScannedFile


class TestScannedFile:
    def test_scanned_file_creation(self, tmp_path):
        """ScannedFile should be created with correct attributes."""
        file_path = tmp_path / "test.md"
        file_path.write_text("# Test")
        stat = file_path.stat()
        
        sf = ScannedFile(
            path=file_path,
            mtime=stat.st_mtime,
            size=stat.st_size
        )
        
        assert sf.path == file_path
        assert sf.mtime == stat.st_mtime
        assert sf.size == stat.st_size

    def test_scanned_file_equality(self, tmp_path):
        """ScannedFiles with same attributes should be equal."""
        file_path = tmp_path / "test.md"
        file_path.write_text("# Test")
        stat = file_path.stat()
        
        sf1 = ScannedFile(path=file_path, mtime=stat.st_mtime, size=stat.st_size)
        sf2 = ScannedFile(path=file_path, mtime=stat.st_mtime, size=stat.st_size)
        
        assert sf1 == sf2

    def test_scanned_file_different_path(self, tmp_path):
        """ScannedFiles with different paths should not be equal."""
        file1 = tmp_path / "a.md"
        file2 = tmp_path / "b.md"
        file1.write_text("# A")
        file2.write_text("# B")
        
        sf1 = ScannedFile(path=file1, mtime=0, size=10)
        sf2 = ScannedFile(path=file2, mtime=0, size=10)
        
        assert sf1 != sf2

    def test_scanned_file_different_mtime(self, tmp_path):
        """ScannedFiles with different mtime should not be equal."""
        file_path = tmp_path / "test.md"
        file_path.write_text("# Test")
        
        sf1 = ScannedFile(path=file_path, mtime=100, size=10)
        sf2 = ScannedFile(path=file_path, mtime=200, size=10)
        
        assert sf1 != sf2

    def test_scanned_file_different_size(self, tmp_path):
        """ScannedFiles with different size should not be equal."""
        file_path = tmp_path / "test.md"
        file_path.write_text("# Test")
        
        sf1 = ScannedFile(path=file_path, mtime=0, size=10)
        sf2 = ScannedFile(path=file_path, mtime=0, size=20)
        
        assert sf1 != sf2

    def test_scanned_file_hashable(self, tmp_path):
        """ScannedFile should be usable in sets and as dict keys."""
        file_path = tmp_path / "test.md"
        file_path.write_text("# Test")
        stat = file_path.stat()
        
        sf = ScannedFile(path=file_path, mtime=stat.st_mtime, size=stat.st_size)
        
        # Should be usable in set
        s = {sf}
        assert sf in s
        
        # Should be usable as dict key
        d = {sf: "value"}
        assert d[sf] == "value"