from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import suppress
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from memsearch import cli as cli_module


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["--version"],
        ["--invalid-option"],
    ],
)
def test_cli_reconfigures_streams_before_root_eager_exits(monkeypatch, args) -> None:
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

    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    with suppress(click.UsageError):
        cli_module.cli.main(args=args, prog_name="memsearch", standalone_mode=False)

    assert stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert stderr.encoding.lower().replace("_", "-") == "utf-8"
    assert stdout.errors == "replace"
    assert stderr.errors == "replace"

    stdout.flush()
    stderr.flush()
    stdout_buffer.getvalue().decode("utf-8")
    stderr_buffer.getvalue().decode("utf-8")


def test_cli_streams_replace_surrogates(monkeypatch) -> None:
    stdout_buffer = io.BytesIO()
    stderr_buffer = io.BytesIO()

    stdout = io.TextIOWrapper(stdout_buffer, encoding="cp1252", errors="strict")
    stderr = io.TextIOWrapper(stderr_buffer, encoding="cp1252", errors="strict")

    monkeypatch.setattr(
        cli_module,
        "sys",
        SimpleNamespace(stdout=stdout, stderr=stderr),
    )

    cli_module._configure_cli_streams()

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


def test_click_runner_capture_remains_supported() -> None:
    result = CliRunner().invoke(cli_module.cli, ["--version"])

    assert result.exit_code == 0
    assert "version" in result.output


def test_import_does_not_reconfigure_streams() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import sys; before = sys.stdout.encoding; import memsearch.cli; print(before, sys.stdout.encoding)"),
        ],
        env={
            **os.environ,
            "PYTHONIOENCODING": "cp1252:strict",
        },
        capture_output=True,
    )

    assert proc.returncode == 0, proc.stderr.decode("cp1252", "replace")
    assert proc.stdout.decode("cp1252").strip() == "cp1252 cp1252"


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
            "--json-output",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONIOENCODING": "cp1252",
        },
        capture_output=True,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    output = proc.stdout.decode("utf-8")
    assert "amyloid-β-notes" in output
    assert isinstance(json.loads(output), dict)
