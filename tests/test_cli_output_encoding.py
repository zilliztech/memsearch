from __future__ import annotations

import io
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from memsearch import cli as cli_module


def test_cli_entrypoint_reconfigures_redirected_streams(monkeypatch) -> None:
    stdout_buffer = io.BytesIO()
    stderr_buffer = io.BytesIO()

    stdout = io.TextIOWrapper(
        stdout_buffer,
        encoding="cp1252",
        errors="strict",
    )
    stderr = io.TextIOWrapper(
        stderr_buffer,
        encoding="cp1252",
        errors="strict",
    )

    monkeypatch.setattr(
        cli_module,
        "sys",
        SimpleNamespace(stdout=stdout, stderr=stderr),
    )

    callback = cli_module.cli.callback
    assert callback is not None
    callback()

    assert stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert stderr.encoding.lower().replace("_", "-") == "utf-8"
    assert stdout.errors == "replace"
    assert stderr.errors == "replace"

    stdout.write(f"Amyloid-β clearance {chr(0xDCFF)}\n")
    stderr.write(f"Heading: 非拉丁字符 {chr(0xDCFF)}\n")
    stdout.flush()
    stderr.flush()

    stdout_text = stdout_buffer.getvalue().decode("utf-8")
    stderr_text = stderr_buffer.getvalue().decode("utf-8")

    assert "Amyloid-β clearance" in stdout_text
    assert "Heading: 非拉丁字符" in stderr_text
    assert "?" in stdout_text
    assert "?" in stderr_text


@pytest.mark.parametrize("exception_type", [AttributeError, OSError])
def test_configure_cli_streams_ignores_unsupported_streams(
    monkeypatch,
    exception_type,
) -> None:
    class UnsupportedStream:
        def reconfigure(self, **_kwargs) -> None:
            raise exception_type()

    monkeypatch.setattr(
        cli_module,
        "sys",
        SimpleNamespace(
            stdout=UnsupportedStream(),
            stderr=UnsupportedStream(),
        ),
    )

    cli_module._configure_cli_streams()


def test_redirected_output_survives_a_legacy_code_page(tmp_path) -> None:
    (tmp_path / ".memsearch.toml").write_text(
        '[index]\nnotes_dir = "/tmp/amyloid-β-notes"\n',
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "memsearch",
            "config",
            "list",
            "--project",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONIOENCODING": "cp1252",
        },
        capture_output=True,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "amyloid-β-notes" in proc.stdout.decode("utf-8")
