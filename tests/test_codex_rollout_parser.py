from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_parse_rollout_supports_flat_transcript_lines(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(
        "\n".join(
            [
                json.dumps({"type": "task_started"}),
                json.dumps({"type": "user_message", "message": "Summarize the battery issue"}),
                json.dumps({"type": "function_call", "name": "read_file", "arguments": {"path": "notes.md"}}),
                json.dumps({"type": "function_call_output", "output": "voltage sag found"}),
                json.dumps({"type": "agent_message", "message": "The issue is voltage sag under load."}),
            ]
        )
        + "\n"
    )

    script = Path("plugins/codex/scripts/parse-rollout.sh")
    result = subprocess.run(["bash", str(script), str(rollout)], capture_output=True, text=True, check=True)

    output = result.stdout
    assert "[Human]: Summarize the battery issue" in output
    assert "[Codex calls tool]: read_file(path=notes.md)" in output
    assert "[Tool output]: voltage sag found" in output
    assert "[Codex]: The issue is voltage sag under load." in output
