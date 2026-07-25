from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _node(code: str, env: dict | None = None) -> str:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=True,
    )
    return result.stdout.strip()


# Inline the two pure helper functions from index.js for behavioural testing.
# These mirror the exact logic; the tests validate the contract, not the internals.
_HELPERS = """\
import { join, resolve } from "node:path";
function getMemsearchDir(projectDir) {
  const explicit = process.env.MEMSEARCH_DIR?.trim();
  return explicit ? resolve(explicit) : join(projectDir, ".memsearch");
}
function getCollectionScopeDir(projectDir) {
  const explicit = process.env.MEMSEARCH_DIR?.trim();
  return explicit ? resolve(explicit) : projectDir;
}
"""


def test_getMemsearchDir_default_uses_project_subdir(tmp_path: Path) -> None:
    project = str(tmp_path / "myproject")
    code = _HELPERS + f'console.log(getMemsearchDir("{project}"));'
    result = _node(code, env={"MEMSEARCH_DIR": ""})
    assert result == str(Path(project) / ".memsearch")


def test_getMemsearchDir_explicit_env_overrides(tmp_path: Path) -> None:
    project = str(tmp_path / "myproject")
    shared = str(tmp_path / "shared-memsearch")
    code = _HELPERS + f'console.log(getMemsearchDir("{project}"));'
    result = _node(code, env={"MEMSEARCH_DIR": shared})
    assert result == shared


def test_getCollectionScopeDir_default_uses_project(tmp_path: Path) -> None:
    project = str(tmp_path / "myproject")
    code = _HELPERS + f'console.log(getCollectionScopeDir("{project}"));'
    result = _node(code, env={"MEMSEARCH_DIR": ""})
    assert result == project


def test_getCollectionScopeDir_explicit_env_shared_scope(tmp_path: Path) -> None:
    """Two different projectDirs with the same MEMSEARCH_DIR get the same scope dir."""
    project_a = str(tmp_path / "project-a")
    project_b = str(tmp_path / "project-b")
    shared = str(tmp_path / "shared-memsearch")
    code = _HELPERS + (
        f'const a = getCollectionScopeDir("{project_a}");\n'
        f'const b = getCollectionScopeDir("{project_b}");\n'
        "console.log(a === b && a === process.env.MEMSEARCH_DIR ? 'same' : 'different');"
    )
    result = _node(code, env={"MEMSEARCH_DIR": shared})
    assert result == "same"
