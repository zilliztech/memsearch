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


def _hook_scope(common: Path, project_dir: Path, env: dict[str, str]) -> tuple[str, str]:
    result = subprocess.run(
        ["bash", "-c", f'source "{common}" </dev/null; printf "%s\\n%s\\n" "$MEMORY_DIR" "$COLLECTION_NAME"'],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    memory_dir, collection = result.stdout.splitlines()
    return memory_dir, collection


def test_worktree_scope_main_shares_the_main_checkout(tmp_path: Path) -> None:
    import os

    repo = (tmp_path / "repository").resolve()
    linked = (tmp_path / "linked-worktree").resolve()
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q", str(repo)],
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "i"],
        ["git", "-C", str(repo), "worktree", "add", "-qb", "linked", str(linked)],
    ):
        subprocess.run(cmd, check=True)

    common = Path("plugins/claude-code/hooks/common.sh").resolve()
    derive = Path("plugins/claude-code/scripts/derive-collection.sh").resolve()
    base = {k: v for k, v in os.environ.items() if k not in ("MEMSEARCH_DIR", "MEMSEARCH_WORKTREE_SCOPE")}

    def scopes(project: Path, env: dict[str, str]) -> tuple[str, str, str]:
        memory_dir, collection = _hook_scope(common, project, {**env, "CLAUDE_PROJECT_DIR": str(project)})
        workspace = subprocess.run(
            ["bash", str(derive), "--workspace"], cwd=project, check=True, capture_output=True, text=True, env=env
        ).stdout.strip()
        return memory_dir, collection, workspace

    shared = {**base, "MEMSEARCH_WORKTREE_SCOPE": "main"}
    repo_scope = scopes(repo, shared)
    assert repo_scope[0] == str(repo / ".memsearch" / "memory")
    assert repo_scope[1] == repo_scope[2]
    assert scopes(linked, shared) == repo_scope

    isolated = scopes(linked, base)
    assert isolated[0] == str(linked / ".memsearch" / "memory")
    assert isolated[1] != repo_scope[1]
    assert isolated[1] == isolated[2]
