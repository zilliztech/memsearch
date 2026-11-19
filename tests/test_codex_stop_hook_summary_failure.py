from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path("plugins/codex/hooks/stop.sh")

# Mimics codex-cli signed in with a ChatGPT account: models it does not accept
# fail with a 400 on stderr and exit status 1 (issue #785).
FAKE_CODEX = """#!/usr/bin/env bash
model=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-m" ]; then model="$2"; shift; fi
  shift
done
printf '%s\\n' "$model" >> "$MEMSEARCH_TEST_MODELS"
if [ "$model" != "$MEMSEARCH_TEST_ACCEPTED_MODEL" ]; then
  echo "ERROR: The '$model' model is not supported when using Codex with a ChatGPT account." >&2
  exit 1
fi
echo "- Codex summarized the turn."
"""


def _run_worker(tmp_path: Path, accepted_model: str, *, timeout_status: int | None = None) -> tuple[str, list[str]]:
    memory_dir = tmp_path / ".memsearch" / "memory"
    memory_dir.mkdir(parents=True)
    memory_file = memory_dir / "2026-11-04.md"
    work_file = tmp_path / "work.json"
    work_file.write_text(
        json.dumps(
            {
                "now": "09:00",
                "memory_file": str(memory_file),
                "session_id": "test-session",
                "transcript_path": str(tmp_path / "rollout.jsonl"),
                "content": "[User] fix the bug\n[Codex] fixed it",
                "user_question": "fix the bug",
                "last_msg": "fixed it",
            }
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in {"codex": FAKE_CODEX, "memsearch": "#!/usr/bin/env bash\nexit 0\n"}.items():
        path = fake_bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    if timeout_status is not None:
        # Stands in for coreutils `timeout`: the hook only looks at its exit status.
        path = fake_bin / "timeout"
        path.write_text(f"#!/usr/bin/env bash\nexit {timeout_status}\n", encoding="utf-8")
        path.chmod(0o755)

    models_log = tmp_path / "models.log"
    models_log.touch()  # a stubbed `timeout` never reaches the fake codex
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "MEMSEARCH_PROJECT_DIR": str(tmp_path),
        "MEMSEARCH_SKIP_HOOK_STDIN": "1",
        "MEMSEARCH_TEST_MODELS": str(models_log),
        "MEMSEARCH_TEST_ACCEPTED_MODEL": accepted_model,
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    subprocess.run(["bash", str(SCRIPT), "--worker", str(work_file)], check=True, env=env)
    return memory_file.read_text(encoding="utf-8"), models_log.read_text(encoding="utf-8").split()


def test_codex_stop_default_model_is_accepted_by_chatgpt_account(tmp_path: Path) -> None:
    content, models = _run_worker(tmp_path, accepted_model="gpt-6-luna")

    assert models == ["gpt-6-luna"]
    assert "- Codex summarized the turn." in content
    assert "Memory summary unavailable" not in content


def test_codex_stop_marks_failed_summary_instead_of_passing_off_fallback(tmp_path: Path) -> None:
    content, _ = _run_worker(tmp_path, accepted_model="some-other-model")

    assert "- Memory summary unavailable: summarizer exited with status 1" in content
    # The excerpt is still kept below the marker so nothing is lost.
    assert "- User asked: fix the bug" in content
    assert "- Codex: fixed it" in content
    assert content.index("Memory summary unavailable") < content.index("- User asked:")


def test_codex_stop_marks_timed_out_summary(tmp_path: Path) -> None:
    # status 124 is what `timeout` returns when it kills the summarizer
    content, _ = _run_worker(tmp_path, accepted_model="gpt-6-luna", timeout_status=124)

    assert "- Memory summary unavailable: summarizer timed out" in content
    assert "summarizer exited with status" not in content
    assert "- User asked: fix the bug" in content
    assert content.index("Memory summary unavailable") < content.index("- User asked:")
