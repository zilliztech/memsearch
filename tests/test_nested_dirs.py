"""Tests for nested directory scanning."""

from pathlib import Path
from memsearch.scanner import scan_paths


def test_scan_deeply_nested_directories(tmp_path: Path):
    """Test scanner handles deeply nested structures."""
    # Create 5 levels of nesting
    current = tmp_path
    for i in range(5):
        current = current / f"level{i}"
        current.mkdir()
    
    # Create files at various levels
    (tmp_path / "root.md").write_text("# Root")
    (tmp_path / "level0" / "l0.md").write_text("# L0")
    (tmp_path / "level0" / "level1" / "l1.md").write_text("# L1")
    (current / "deep.md").write_text("# Deep")
    
    results = scan_paths([tmp_path])
    paths = {r.path.name for r in results}
    
    assert "root.md" in paths
    assert "l0.md" in paths
    assert "l1.md" in paths
    assert "deep.md" in paths


def test_scan_wide_directory_structure(tmp_path: Path):
    """Test scanner handles wide directory with many siblings."""
    # Create many sibling directories
    for i in range(10):
        sibling = tmp_path / f"sibling{i}"
        sibling.mkdir()
        (sibling / f"file{i}.md").write_text(f"# File {i}")
    
    results = scan_paths([tmp_path])
    paths = {r.path.name for r in results}
    
    for i in range(10):
        assert f"file{i}.md" in paths