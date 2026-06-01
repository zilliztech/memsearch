from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path("plugins/codex/hooks/stop.sh")


def test_codex_stop_worker_fallback_summary_preserves_utf8(tmp_path: Path) -> None:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    memory_file = memory_dir / "2026-06-01.md"
    work_file = tmp_path / "work.json"
    long_cyrillic_message = "Привет мир, проверяем безопасную обрезку UTF-8. " * 120

    work_file.write_text(
        json.dumps(
            {
                "now": "15:10",
                "memory_file": str(memory_file),
                "session_id": "test-session",
                "transcript_path": str(tmp_path / "rollout.jsonl"),
                "content": "fallback content",
                "user_question": "как поправить?",
                "last_msg": long_cyrillic_message,
            }
        ),
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "MEMSEARCH_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_SKIP_HOOK_STDIN": "1",
        # Keep codex/memsearch out of PATH so the worker uses fallback summary.
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    }
    subprocess.run(["bash", str(SCRIPT), "--worker", str(work_file)], check=True, env=env)

    content = memory_file.read_text(encoding="utf-8")
    assert "- User asked: как поправить?" in content
    assert "- Codex: Привет мир" in content
    assert "..." in content
