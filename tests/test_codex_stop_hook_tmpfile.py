from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path("plugins/codex/hooks/stop.sh").resolve()


def test_codex_stop_captures_use_distinct_files_and_preserve_existing_input(tmp_path: Path) -> None:
    """Exercise the public hook with the platform's real mktemp and two workers."""
    temporary_dir = tmp_path / "shared temporary files"
    temporary_dir.mkdir()
    occupied = temporary_dir / "memsearch-stop.XXXXXX.json"
    occupied.write_text("another capture owns this file", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    scripts = {
        "memsearch": "#!/bin/sh\nexit 0\n",
        "codex": '#!/bin/sh\nprintf "%s\\n" "- $MEMSEARCH_TEST_MARKER"\n',
        "mktemp": (
            '#!/bin/sh\nfile=$("$MEMSEARCH_TEST_MKTEMP" "$@") || exit "$?"\n'
            'printf "%s\\n" "$file" > "$MEMSEARCH_TEST_ALLOCATION"\n'
            'printf "%s\\n" "$file"\n'
        ),
        "python3": (
            '#!/bin/sh\ncase "$1" in\n'
            '  */maintenance-runner.py) : > "$MEMSEARCH_TEST_DONE"; exit 0 ;;\n'
            'esac\nexec "$MEMSEARCH_TEST_PYTHON" "$@"\n'
        ),
    }
    for name, content in scripts.items():
        executable = fake_bin / name
        executable.write_text(content, encoding="utf-8")
        executable.chmod(0o755)

    # /usr/bin/mktemp is BSD on macOS and GNU on Linux. Only log its output;
    # do not emulate either implementation or replace the hook's allocation.
    mktemp = shutil.which("mktemp", path="/usr/bin:/bin")
    assert mktemp is not None
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "TMPDIR": str(temporary_dir),
        # Keep the fixture first: common.sh prepends /usr/local/bin if absent.
        "PATH": f"{fake_bin}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "MEMSEARCH_NO_WATCH": "1",
        "MEMSEARCH_SKIP_HOOK_STDIN": "0",
        "MEMSEARCH_IN_STOP_WORKER": "",
        "MEMSEARCH_TEST_MKTEMP": mktemp,
        "MEMSEARCH_TEST_PYTHON": sys.executable,
    }

    def capture(index: int) -> Path:
        project = tmp_path / f"project-{index}"
        project.mkdir()
        memory = project / ".memsearch"
        marker = f"capture-{index}-记忆"
        done = project / "worker-done"
        allocation = project / "allocated-path"
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            input=json.dumps({"session_id": f"session-{index}", "last_assistant_message": marker}),
            capture_output=True,
            text=True,
            cwd=project,
            env={
                **environment,
                "MEMSEARCH_PROJECT_DIR": str(project),
                "MEMSEARCH_DIR": str(memory),
                "MEMSEARCH_TEST_MARKER": marker,
                "MEMSEARCH_TEST_DONE": str(done),
                "MEMSEARCH_TEST_ALLOCATION": str(allocation),
            },
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "{}\n"
        assert result.stderr == ""

        # The maintenance boundary follows the real worker's journal append.
        # Stub it to avoid unrelated background tasks or dependency downloads.
        deadline = time.monotonic() + 15
        while not done.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert done.exists(), "capture worker did not finish"
        journals = list((memory / "memory").glob("*.md"))
        assert len(journals) == 1
        journal = journals[0].read_text(encoding="utf-8")
        assert f"- {marker}" in journal
        assert f"<!-- session:session-{index} " in journal
        allocated = Path(allocation.read_text(encoding="utf-8").strip())
        assert allocated.parent == temporary_dir
        assert not allocated.exists(), "worker must consume and remove its own input"
        return allocated

    with ThreadPoolExecutor(max_workers=2) as executor:
        allocated = list(executor.map(capture, range(2)))
    assert allocated[0] != allocated[1]
    assert occupied.read_text(encoding="utf-8") == "another capture owns this file"
    assert list(temporary_dir.iterdir()) == [occupied]
