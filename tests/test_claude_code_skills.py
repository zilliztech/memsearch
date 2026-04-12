from __future__ import annotations

from pathlib import Path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_claude_code_skill_files_exist() -> None:
    skills_root = Path("plugins/claude-code/skills")
    assert (skills_root / "memory-recall" / "SKILL.md").exists()
    assert (skills_root / "memory-search" / "SKILL.md").exists()
    assert (skills_root / "memory-expand" / "SKILL.md").exists()
    assert (skills_root / "session-recall" / "SKILL.md").exists()
    assert (skills_root / "memory-stats" / "SKILL.md").exists()
    assert (skills_root / "config-check" / "SKILL.md").exists()
    assert (skills_root / "memory-router" / "SKILL.md").exists()


def test_memory_search_skill_metadata() -> None:
    text = _read_text(Path("plugins/claude-code/skills/memory-search/SKILL.md"))
    assert "name: memory-search" in text
    assert "context: fork" in text
    assert "allowed-tools: Bash" in text
    assert 'memsearch search "<query>" --top-k 8 --json-output' in text


def test_memory_expand_skill_metadata() -> None:
    text = _read_text(Path("plugins/claude-code/skills/memory-expand/SKILL.md"))
    assert "name: memory-expand" in text
    assert "context: fork" in text
    assert "allowed-tools: Bash" in text
    assert "memsearch expand <chunk_hash>" in text


def test_session_diagnostic_and_router_skill_metadata() -> None:
    session_text = _read_text(Path("plugins/claude-code/skills/session-recall/SKILL.md"))
    stats_text = _read_text(Path("plugins/claude-code/skills/memory-stats/SKILL.md"))
    config_text = _read_text(Path("plugins/claude-code/skills/config-check/SKILL.md"))
    router_text = _read_text(Path("plugins/claude-code/skills/memory-router/SKILL.md"))

    assert "name: session-recall" in session_text
    assert "name: memory-stats" in stats_text
    assert "name: config-check" in config_text
    assert "name: memory-router" in router_text
    assert "memsearch search \"<topic query> <session_id>\"" in session_text
    assert "Fallback to direct markdown/session anchor reading only if the memsearch path is insufficient" in session_text
    assert "memsearch stats --collection" in stats_text
    assert "memsearch config list --resolved" in config_text
    assert "memsearch-first retrieval" in router_text
    assert "retrieval readiness" in router_text
    assert "wrong memory system" in router_text
