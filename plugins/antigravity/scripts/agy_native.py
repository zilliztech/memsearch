"""Isolated native generation using a bundled tool-free custom agent."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

DEFAULT_MODEL = "gemini-4-hydrogen-low"


class NativeGenerationError(RuntimeError):
    """A safe diagnostic that never includes raw provider output or prompt text."""

    def __init__(self, reason: str):
        self.safe_reason = reason
        super().__init__(reason)


def generate(prompt: str, *, model: str = "", timeout: int = 180) -> str:
    plugin = Path(__file__).resolve().parents[1]
    env = {**os.environ, "MEMSEARCH_DISABLE": "1", "MEMSEARCH_AGY_HELPER": "1", "MEMSEARCH_NO_WATCH": "1"}
    # Only the bundled custom agent is discovered in this temporary workspace.
    # Authentication remains in the existing HOME; no auth/config is copied.
    with ExitStack() as stack:
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="memsearch-agy-helper-"))
        workspace = Path(directory)
        bundle = workspace / ".agents" / "plugins" / "memsearch"
        agents = bundle / "agents"
        agents.mkdir(parents=True)
        shutil.copyfile(plugin / "plugin.json", bundle / "plugin.json")
        shutil.copyfile(plugin / "agents/memsearch-helper.md", agents / "memsearch-helper.md")
        # Long Unicode journals can exceed both Windows command-line limits
        # and Linux's per-argument limit. Use the official stdin protocol then.
        streamed = len(prompt.encode("utf-8")) > 24000
        stdin = subprocess.DEVNULL
        if streamed:
            stdin = stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
            stdin.write((json.dumps({"event": "user", "message": {"content": prompt}}) + "\n").encode("utf-8"))
            stdin.seek(0)
        command = [
            shutil.which("agy") or str(Path.home() / ".local/bin/agy"),
            "--agent",
            "memsearch-helper",
            *(["--input-format", "stream-json"] if streamed else ["-p", prompt]),
            "--model",
            model or DEFAULT_MODEL,
            "--output-format",
            "stream-json" if streamed else "json",
            "--disable-slash-commands",
            "--print-timeout",
            f"{timeout}s",
        ]
        settings = os.environ.get("MEMSEARCH_ANTIGRAVITY_SETTINGS")
        if settings:
            if not settings.lstrip().startswith("{"):
                settings = str(Path(settings).expanduser().resolve())
            command += ["--settings", settings]
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=env,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            stdout, _stderr = process.communicate(timeout=timeout + 15)
        except subprocess.TimeoutExpired:
            import psutil

            try:
                parent = psutil.Process(process.pid)
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()
            except psutil.NoSuchProcess:
                pass
            process.communicate(timeout=5)
            raise NativeGenerationError("Antigravity helper timed out") from None
    # Never accept diagnostics as model output or persist raw provider errors.
    if process.returncode:
        detail = stdout.lower()
        if "invalid model" in detail or "not recognized as a known model" in detail:
            raise NativeGenerationError("Antigravity rejected the configured model; choose an available native model.")
        raise NativeGenerationError(
            f"Antigravity helper exited with status {process.returncode}; check native model access."
        )
    try:
        if streamed:
            results = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            finals = [row["result"] for row in results if isinstance(row, dict) and row.get("event") == "result"]
            result = finals[0] if len(finals) == 1 else None
        else:
            result = json.loads(stdout)
    except (KeyError, ValueError):
        raise NativeGenerationError("Antigravity helper returned invalid JSON") from None
    if not isinstance(result, dict) or result.get("status") != "SUCCESS":
        raise NativeGenerationError("Antigravity helper did not report SUCCESS")
    response = result.get("response")
    if not isinstance(response, str) or not response.strip():
        raise NativeGenerationError("Antigravity helper returned an empty response")
    return response.strip()
