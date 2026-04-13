from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_claude_code_skill_files_exist() -> None:
    skills_root = REPO_ROOT / "plugins/claude-code/skills"
    assert (skills_root / "memory-recall" / "SKILL.md").exists()
    assert (skills_root / "memory-search" / "SKILL.md").exists()
    assert (skills_root / "memory-expand" / "SKILL.md").exists()
    assert (skills_root / "session-recall" / "SKILL.md").exists()
    assert (skills_root / "memory-stats" / "SKILL.md").exists()
    assert (skills_root / "config-check" / "SKILL.md").exists()
    assert (skills_root / "memory-router" / "SKILL.md").exists()


def test_memory_search_skill_metadata() -> None:
    text = _read_text(REPO_ROOT / "plugins/claude-code/skills/memory-search/SKILL.md")
    assert "name: memory-search" in text
    assert "context: fork" in text
    assert "allowed-tools: Bash" in text
    assert 'memsearch search "<query>" --top-k 8 --json-output' in text
    assert "Try indexed memsearch search first" in text
    assert "Use direct memory-file scanning only as a bounded fallback" in text
    assert "Keep `memsearch search` as the primary path" in text
    assert "whether the result came from indexed memsearch search or bounded direct memory-file fallback" in text


def test_memory_expand_skill_metadata() -> None:
    text = _read_text(REPO_ROOT / "plugins/claude-code/skills/memory-expand/SKILL.md")
    assert "name: memory-expand" in text
    assert "context: fork" in text
    assert "allowed-tools: Bash" in text
    assert "memsearch expand <chunk_hash>" in text


def test_session_diagnostic_and_router_skill_metadata() -> None:
    session_text = _read_text(REPO_ROOT / "plugins/claude-code/skills/session-recall/SKILL.md")
    stats_text = _read_text(REPO_ROOT / "plugins/claude-code/skills/memory-stats/SKILL.md")
    config_text = _read_text(REPO_ROOT / "plugins/claude-code/skills/config-check/SKILL.md")
    router_text = _read_text(REPO_ROOT / "plugins/claude-code/skills/memory-router/SKILL.md")

    assert "name: session-recall" in session_text
    assert "name: memory-stats" in stats_text
    assert "name: config-check" in config_text
    assert "name: memory-router" in router_text
    assert "memsearch search \"<session_id>\"" in session_text
    assert "memsearch search \"<topic query> <session_id>\"" in session_text
    assert "Always attempt memsearch search first" in session_text
    assert "Fallback to direct markdown/session anchor reading only if the memsearch path is genuinely insufficient" in session_text
    assert "the user gave only a session id with no meaningful semantic query" not in session_text
    assert "session-recall` should still attempt memsearch search first, including for a bare session id" in router_text
    assert "memsearch stats --collection" in stats_text
    assert "memsearch config list --resolved" in config_text
    assert "memsearch-first retrieval" in router_text
    assert "retrieval readiness" in router_text
    assert "wrong memory system" in router_text
