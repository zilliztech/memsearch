from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from memsearch.config import resolve_config, save_config


def _derive_collection(script: Path, project_dir: Path) -> str:
    result = subprocess.run(
        ["bash", str(script), str(project_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_linked_worktree_defaults_are_isolated_but_explicit_collection_can_be_shared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repository"
    linked = tmp_path / "linked-worktree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-qb", "linked", str(linked)],
        check=True,
    )

    script = Path("plugins/claude-code/scripts/derive-collection.sh").resolve()
    repo_default = _derive_collection(script, repo)
    linked_default = _derive_collection(script, linked)
    assert repo_default != linked_default

    monkeypatch.setattr("memsearch.config.GLOBAL_CONFIG_PATH", tmp_path / "no-global.toml")
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", repo / ".memsearch.toml")
    repo_cfg = resolve_config(default_overrides={"milvus": {"collection": repo_default}})
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", linked / ".memsearch.toml")
    linked_cfg = resolve_config(default_overrides={"milvus": {"collection": linked_default}})
    assert repo_cfg.milvus.collection != linked_cfg.milvus.collection

    for project in (repo, linked):
        save_config({"milvus": {"collection": "shared_worktree_memory"}}, project / ".memsearch.toml")
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", repo / ".memsearch.toml")
    repo_shared = resolve_config(default_overrides={"milvus": {"collection": repo_default}})
    monkeypatch.setattr("memsearch.config.PROJECT_CONFIG_PATH", linked / ".memsearch.toml")
    linked_shared = resolve_config(default_overrides={"milvus": {"collection": linked_default}})
    assert repo_shared.milvus.collection == linked_shared.milvus.collection == "shared_worktree_memory"
