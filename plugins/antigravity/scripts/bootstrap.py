"""Select the checkout or installed MemSearch interpreter without installing anything."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def bootstrap(entrypoint: Path) -> None:
    source = next((p for p in entrypoint.resolve().parents if (p / "src/memsearch").is_dir()), None)
    if source:
        # Always use this checkout's core, even when another release is installed.
        sys.path.insert(0, str(source / "src"))
        python = source / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    else:
        python = None
        executable = shutil.which("memsearch")
        if executable:
            first = Path(executable).read_text(encoding="utf-8", errors="replace").splitlines()[0]
            if first.startswith("#!"):
                python = Path(first[2:].strip())
    if (
        python
        and python.is_file()
        and os.path.abspath(sys.executable) != str(python)
        and os.environ.get("MEMSEARCH_AGY_BOOTSTRAPPED") != "1"
    ):
        os.execve(
            str(python),
            [str(python), str(entrypoint), *sys.argv[1:]],
            {**os.environ, "MEMSEARCH_AGY_BOOTSTRAPPED": "1"},
        )


def require_core() -> None:
    from memsearch.config import PluginsConfig
    from memsearch.transcript import _PARSERS

    if not hasattr(PluginsConfig(), "antigravity") or "antigravity" not in _PARSERS:
        raise RuntimeError(
            "Install MemSearch from the Antigravity source checkout with uv tool install --force '/path/to/checkout[onnx]'."
        )
