"""Enforce that per-platform skill copies stay in sync with the canonical source.

The canonical, platform-independent skill bodies live under
``plugins/_shared/skills/``. ``scripts/sync-skills.sh`` materializes them into
each platform's ``plugins/<platform>/skills/`` directory, prepending that
platform's own frontmatter. These copies are committed so each platform package
ships self-contained skills (a plugin install only bundles its own directory,
so it cannot depend on ``_shared`` at runtime).

Scope: ``memory-config`` and ``memory-to-skill`` (the two platform-independent
skills). ``memory-recall`` is deliberately NOT checked here — its platform
differences are structural (OpenClaw uses MCP tools; the collection/L3 commands
embed install-time path placeholders), so it is hand-maintained per platform.

This mirrors ``tests/test_maintenance_runner.py``, which enforces the same
copy-match invariant for ``maintenance-runner.py``.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "plugins" / "_shared" / "skills"

# Skills materialized from a shared body plus per-platform frontmatter.
FS_PLATFORMS = ("claude-code", "codex", "openclaw", "opencode")

# Extra frontmatter lines each platform adds after the shared ``description:`` line.
FRONTMATTER_EXTRA = {
    "claude-code": ["context: fork", "allowed-tools: Bash"],
    "codex": [],
    "openclaw": ["metadata:", "  openclaw:", '    emoji: "🧠"'],
    "opencode": ["allowed-tools: Bash"],
}


def _split_frontmatter(text: str) -> tuple[str, list[str], str]:
    """Return (name, frontmatter_lines_between_name_and_close, body)."""
    lines = text.splitlines()
    assert lines[0].strip() == "---", "expected leading ---"
    assert lines[1].startswith("name:"), "expected name: on line 2"
    name = lines[1].split(":", 1)[1].strip()
    close_idx = None
    for i in range(2, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break
    assert close_idx is not None, "no closing --- found"
    middle = lines[2:close_idx]
    body = "\n".join(lines[close_idx + 1 :]).lstrip("\n")
    return name, middle, body


def test_skill_copies_match_shared() -> None:
    for skill in ("memory-config", "memory-to-skill"):
        shared_path = SHARED / skill / "SKILL.md"
        assert shared_path.is_file(), f"missing shared source {shared_path}"
        shared_text = shared_path.read_text(encoding="utf-8")
        shared_name, shared_middle, shared_body = _split_frontmatter(shared_text)

        for platform in FS_PLATFORMS:
            copied = ROOT / "plugins" / platform / "skills" / skill / "SKILL.md"
            assert copied.is_file(), f"missing copy {copied}"
            copied_text = copied.read_text(encoding="utf-8")
            name, middle, body = _split_frontmatter(copied_text)

            assert name == shared_name, f"{skill}/{platform}: name mismatch"
            expected_middle = [shared_middle[0], *FRONTMATTER_EXTRA[platform]]
            assert middle == expected_middle, (
                f"{skill}/{platform}: frontmatter mismatch\n  got:      {middle}\n  expected: {expected_middle}"
            )
            assert body == shared_body, f"{skill}/{platform}: body drifted from shared source"


def test_skill_references_match_shared() -> None:
    """The references/ directory must be byte-identical across every copy."""
    for skill in ("memory-config", "memory-to-skill"):
        shared_refs = SHARED / skill / "references"
        assert shared_refs.is_dir(), f"missing shared references {shared_refs}"

        shared_files = {
            p.relative_to(shared_refs): p.read_bytes() for p in sorted(shared_refs.rglob("*")) if p.is_file()
        }

        for platform in (*FS_PLATFORMS, "dsh"):
            refs = ROOT / "plugins" / platform / "skills" / skill / "references"
            assert refs.is_dir(), f"missing references {refs}"
            copied_files = {p.relative_to(refs): p.read_bytes() for p in sorted(refs.rglob("*")) if p.is_file()}
            assert copied_files == shared_files, f"{skill}/{platform}: references/ drifted from shared source"
