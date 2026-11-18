"""Small real-process regressions; no installed core, model, or database required."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("MEMSEARCH_RUNTIME_ROOT", Path(__file__).resolve().parents[3]))


def test_maintenance_timeout_stops_descendants_and_can_retry(tmp_path):
    import runpy

    import psutil

    runner = runpy.run_path(str(ROOT / "plugins/_shared/scripts/maintenance-runner.py"))
    child_pid = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time; from pathlib import Path; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
    )
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            runner["run_command"](
                [sys.executable, "-c", code, str(child_pid)],
                env=os.environ.copy(),
                cwd=tmp_path,
                timeout=2,
            )
        assert time.monotonic() - started < 10
        pid = int(child_pid.read_text())
        with contextlib.suppress(psutil.NoSuchProcess):
            assert psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        assert (
            runner["run_command"](
                [sys.executable, "-c", "print('retry succeeded')"],
                env=os.environ.copy(),
                cwd=tmp_path,
                timeout=5,
            )
            == "retry succeeded"
        )
    finally:
        if child_pid.exists():
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(int(child_pid.read_text())).kill()


def test_maintenance_timeout_does_not_block_closing_inherited_pipe(tmp_path):
    import runpy

    import psutil

    runner = runpy.run_path(str(ROOT / "plugins/_shared/scripts/maintenance-runner.py"))
    pid_file = tmp_path / "detached-child.pid"
    # The launcher exits before the timeout, so its child's new parent can no
    # longer be discovered through it. Its inherited output pipe stays open.
    code = (
        "import subprocess,sys; from pathlib import Path; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)']); "
        "Path(sys.argv[1]).write_text(str(child.pid))"
    )
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            runner["run_command"](
                [sys.executable, "-c", code, str(pid_file)],
                env=os.environ.copy(),
                cwd=tmp_path,
                timeout=1,
            )
        assert time.monotonic() - started < 10
    finally:
        if pid_file.exists():
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(int(pid_file.read_text())).kill()


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


def _windows_reexec_probe(tmp_path: Path, script: str, *, via_uv=False, streams="open"):
    """Exercise the Node host -> Python -> child chain with real Windows handles."""
    import shutil
    import zipfile

    report = tmp_path / "child.json"
    child = tmp_path / "child.py"
    child.write_text(
        "import ctypes,json,sys\nfrom pathlib import Path\n"
        "payload={'console':ctypes.windll.kernel32.GetConsoleWindow(),'stdin':sys.stdin.read()}\n"
        f"Path({str(report)!r}).write_text(json.dumps(payload))\n"
        "print('摘要 中文 \N{MULTIPLICATION SIGN}')\nprint('child failure detail',file=sys.stderr)\nsys.exit(7)\n",
        encoding="utf-8",
    )
    # An empty local wheel makes uv exercise its --with environment without
    # downloading MemSearch, models, or other runtime dependencies.
    wheel = tmp_path / "memsearch_console_fixture-0.0.0-py3-none-any.whl"
    if via_uv:
        dist = "memsearch_console_fixture-0.0.0.dist-info"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                f"{dist}/METADATA", "Metadata-Version: 2.1\nName: memsearch-console-fixture\nVersion: 0.0.0\n"
            )
            archive.writestr(f"{dist}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            archive.writestr(f"{dist}/RECORD", "")
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import os,runpy,subprocess,sys\n"
        "source,child,uv,streams,wheel=sys.argv[1:]\n"
        "module=runpy.run_path(source)\n"
        "command=[sys.executable,child]\n"
        "if uv:\n"
        "    command=[uv,'run','--offline','--no-project','--no-config','--python',sys.executable,'--with',wheel,'python',child]\n"
        "if streams=='closed':\n"
        "    sys.stdout.close();sys.stderr.close()\n"
        "elif streams=='missing':\n"
        "    sys.stdout=None;sys.stderr=None\n"
        "module['_reexec'](command,os.environ.copy())\n",
        encoding="utf-8",
    )
    host = tmp_path / "host.mjs"
    host.write_text(
        "const cfg=JSON.parse(process.argv[2]);\n"
        "const {spawnCommand}=await import(cfg.runtime);\n"
        "const child=spawnCommand(cfg.python,cfg.args,{detached:cfg.detached});\n"
        "let stdout='',stderr='';\n"
        "child.stdout.setEncoding('utf8').on('data',x=>stdout+=x);\n"
        "child.stderr.setEncoding('utf8').on('data',x=>stderr+=x);\n"
        "child.stdin.end();\n"
        "child.on('close',code=>process.stdout.write(JSON.stringify({code,stdout,stderr})));\n"
        "child.on('error',error=>{console.error(error);process.exit(1)});\n",
        encoding="utf-8",
    )
    uv = shutil.which("uv") if via_uv else ""
    if via_uv:
        assert uv, "the Windows runtime job must provide uv"
    cfg = {
        "runtime": (ROOT / "plugins/dsh/runtime.js").as_uri(),
        "python": sys.executable,
        "args": [str(parent), str(ROOT / "plugins" / script), str(child), uv, streams, str(wheel)],
        "detached": "maintenance-runner" in script,
    }
    result = subprocess.run(
        ["node", str(host), json.dumps(cfg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["code"] == 7, payload
    assert json.loads(report.read_text()) == {"console": 0, "stdin": ""}
    return payload


@pytest.mark.skipif(os.name != "nt", reason="requires Windows console allocation")
@pytest.mark.parametrize("script", ["dsh/scripts/summarize.py", "_shared/scripts/maintenance-runner.py"])
@pytest.mark.parametrize("via_uv", [False, True])
def test_hidden_reexec_preserves_output_and_exit_status(tmp_path, script, via_uv):
    result = _windows_reexec_probe(tmp_path, script, via_uv=via_uv)
    assert result["stdout"].strip() == "摘要 中文 \N{MULTIPLICATION SIGN}"
    assert "child failure detail" in result["stderr"]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows console allocation")
@pytest.mark.parametrize("script", ["dsh/scripts/summarize.py", "_shared/scripts/maintenance-runner.py"])
@pytest.mark.parametrize("streams", ["closed", "missing"])
def test_hidden_reexec_handles_unavailable_host_streams(tmp_path, script, streams):
    result = _windows_reexec_probe(tmp_path, script, streams=streams)
    assert result["stdout"] == result["stderr"] == ""
