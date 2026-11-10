"""Small real-process regressions; no installed core, model, or database required."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("MEMSEARCH_RUNTIME_ROOT", Path(__file__).resolve().parents[3]))


@pytest.mark.parametrize("encoding", ["cp936", "cp1251"])
def test_summary_stdin_uses_utf8(encoding: str) -> None:
    expected = "会议摘要:中文 \N{MULTIPLICATION SIGN} 😀\n"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy,sys; runpy.run_path(sys.argv[1], run_name='probe'); print(sys.stdin.read(), end='')",
            str(ROOT / "plugins/dsh/scripts/summarize.py"),
        ],
        input=expected.encode(),
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": f"{encoding}:strict"},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout.decode("utf-8").replace("\r\n", "\n") == expected


@pytest.mark.parametrize("script", ["dsh/scripts/summarize.py", "_shared/scripts/maintenance-runner.py"])
def test_bootstrap_waits_for_child_and_preserves_exit_status(tmp_path: Path, script: str) -> None:
    """Run the real import bootstrap with a controlled installed CLI/interpreter."""
    entry = tmp_path / "installed helper.py"
    entry.write_text(
        "import json,os,sys,time\n"
        "time.sleep(0.2)\n"
        "print(json.dumps({'marker': os.environ['BOOTSTRAP_MARKER'], "
        "'transcript': os.environ.get('MEMSEARCH_DSH_TRANSCRIPT', '')}))\n"
        "print('child failure detail', file=sys.stderr)\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    # The existing shebang fallback takes the first token as the interpreter.
    # A Python executable in a path without spaces also works on hosted Windows.
    executable = Path(sys.executable)
    if " " in str(executable):
        pytest.skip("bootstrap shebang fixture requires a space-free interpreter path")
    cli = tmp_path / "memsearch"
    cli.write_text(f"#!{executable}\n", encoding="utf-8")
    code = """
import builtins, importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('bootstrap_probe', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.__file__ = sys.argv[2]
original_import = builtins.__import__
def installed_import(name, *args, **kwargs):
    if name == 'memsearch':
        raise ModuleNotFoundError(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = installed_import
resolve_cli = lambda name: sys.argv[3] if name == 'memsearch' else None
if hasattr(module, '_which'):
    module._which = resolve_cli
else:
    module.shutil.which = resolve_cli
if 'summarize' in sys.argv[1]:
    module.ensure_memsearch_importable('保留的对话')
else:
    module.ensure_memsearch_importable(Path(sys.argv[2]))
raise RuntimeError('bootstrap returned instead of handing off')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "plugins" / script), str(entry), str(cli)],
        capture_output=True,
        env={
            **os.environ,
            "BOOTSTRAP_MARKER": "runtime-721",
            "MEMSEARCH_DSH_UV_BOOTSTRAP": "0",
            "MEMSEARCH_MAINTENANCE_UV_BOOTSTRAP": "0",
            "PYTHONIOENCODING": "utf-8",
        },
        timeout=10,
    )
    assert result.returncode == 7, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["marker"] == "runtime-721"
    if "summarize" in script:
        assert payload["transcript"] == "保留的对话"
    assert b"child failure detail" in result.stderr
