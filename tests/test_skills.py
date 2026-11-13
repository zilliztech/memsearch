from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from memsearch import skills as skills_mod
from memsearch.config import MemSearchConfig


def _enable(cfg: MemSearchConfig, *, min_occurrences: int = 3) -> None:
    cfg.plugins.claude_code.memory_to_skill.enabled = True
    cfg.plugins.claude_code.memory_to_skill.min_occurrences = min_occurrences


def _seed_memory(project: Path) -> Path:
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    (memory / "2026-06-12.md").write_text("### 10:00\n- Ran the test suite with pytest.\n", encoding="utf-8")
    return memory


def _one_skill_runner(name: str = "run-tests"):
    def runner(ctx, prompt: str) -> str:
        assert "Recent memory journal entries" in prompt
        return json.dumps(
            {
                "skills": [
                    {
                        "name": name,
                        "description": "Run the project's test suite. Use when asked to run or check tests.",
                        "body": "## Run the tests\n\n1. Run pytest\n2. Report failures",
                        "occurrences": 3,
                        "sources": ["2026-06-12.md"],
                        "reason": "Recurred across sessions.",
                    }
                ]
            }
        )

    return runner


def test_distill_creates_candidate_and_commits(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)

    result = skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=_one_skill_runner())

    assert result.action == "distilled"
    assert result.created == ["run-tests"]

    skill_dir = project / ".memsearch" / "skill-candidates" / "run-tests"
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert skill_md.startswith("---\nname: run-tests\n")
    assert "description:" in skill_md

    meta = json.loads((skill_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "candidate"
    assert meta["content_hash"].startswith("gitblob:")
    assert meta["occurrences"] == 3
    listed = skills_mod.list_candidates(project / ".memsearch")
    assert listed[0]["pending_install"] is True
    assert listed[0]["pending_reason"] == "new"

    # The store is a git repo with at least one commit.
    git_dir = project / ".memsearch" / "skill-candidates" / ".git"
    assert git_dir.is_dir()
    log = subprocess.run(
        ["git", "-C", str(project / ".memsearch" / "skill-candidates"), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "distill" in log.stdout


def test_distill_prompt_preserves_newest_journal_when_corpus_exceeds_budget(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    memory = project / ".memsearch" / "memory"
    memory.mkdir(parents=True)

    oldest = memory / "2026-07-30.md"
    newest = memory / "2026-07-31.md"
    oldest.write_text(
        "OLDEST_JOURNAL_MARKER\n" + "x" * (skills_mod.MAX_PROMPT_CHARS + 1_000),
        encoding="utf-8",
    )
    newest.write_text("NEWEST_JOURNAL_MARKER\n", encoding="utf-8")
    os.utime(oldest, (100, 100))
    os.utime(newest, (200, 200))

    ctx = skills_mod.TaskContext(
        platform="codex",
        task=skills_mod.TASK,
        task_config=skills_mod.PluginMemoryToSkillConfig(),
        project_dir=project,
        memsearch_dir=project / ".memsearch",
        input_dir=memory,
        output_file=project / ".memsearch" / "skill-candidates",
        input_digest="sha256:test",
    )

    prompt = skills_mod._build_distill_prompt(
        ctx,
        min_occurrences=3,
        existing=[],
        cfg=MemSearchConfig(),
    )

    assert "NEWEST_JOURNAL_MARKER" in prompt
    assert "OLDEST_JOURNAL_MARKER" not in prompt
    assert "[older journal entries truncated]" in prompt
    assert len(prompt) <= skills_mod.MAX_PROMPT_CHARS


def test_render_skill_md_has_only_standard_frontmatter() -> None:
    md = skills_mod._render_skill_md("deploy", "Deploy the app", "## Deploy\n\n1. push")
    header = md.split("---", 2)[1]
    # Only name + description in frontmatter; no tracking fields leak in.
    assert "name:" in header
    assert "description:" in header
    for leaked in ("status", "occurrences", "sources", "confidence"):
        assert leaked not in header


def test_distill_skips_unchanged_input(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)

    calls = {"n": 0}

    def counting_runner(ctx, prompt: str) -> str:
        calls["n"] += 1
        return _one_skill_runner()(ctx, prompt)

    first = skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=counting_runner)
    second = skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=counting_runner)

    assert first.action == "distilled"
    assert second.action == "skip"
    assert calls["n"] == 1


def test_distill_disabled_by_default(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()  # memory_to_skill disabled by default

    result = skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=_one_skill_runner())

    assert result.action == "disabled"
    assert result.skipped is True


def test_distill_failure_records_state(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)

    calls = 0

    def runner(ctx, prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("native runner failed")
        return json.dumps({"skills": []})

    with pytest.raises(RuntimeError, match="native runner failed"):
        skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=runner)

    state = json.loads((project / ".memsearch" / ".maintenance-state.json").read_text(encoding="utf-8"))
    task_state = state["claude-code.memory_to_skill"]
    assert task_state["last_action"] == "error"
    assert task_state["last_failed_at"]
    assert task_state["failed_input_digest"].startswith("sha256:")
    assert "native runner failed" in task_state["last_error"]

    retry = skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=runner)
    assert retry.action == "none"
    assert calls == 2


def test_install_copies_to_paths_and_updates_meta(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)
    skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=_one_skill_runner())

    dest = project / ".claude" / "skills"
    installed = skills_mod.install("run-tests", [str(dest)], project_dir=project)

    assert installed == [str(dest / "run-tests" / "SKILL.md")]
    assert (dest / "run-tests" / "SKILL.md").is_file()

    meta_path = project / ".memsearch" / "skill-candidates" / "run-tests" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == "installed"
    assert meta["content_hash"].startswith("gitblob:")
    assert meta["installed_hash"] == meta["content_hash"]
    assert meta["installed_at"]
    assert meta["installed_paths"] == installed
    listed = skills_mod.list_candidates(project / ".memsearch")
    assert listed[0]["pending_install"] is False


def test_install_missing_candidate_raises(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    with pytest.raises(ValueError, match="no candidate skill"):
        skills_mod.install("nope", [str(project / ".claude" / "skills")], project_dir=project)


def test_install_empty_paths_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no install paths"):
        skills_mod.install("x", [], project_dir=tmp_path)


def test_parse_distill_response_filters_incomplete() -> None:
    raw = json.dumps(
        {
            "skills": [
                {"name": "ok", "description": "d", "body": "b"},
                {"name": "no-body", "description": "d", "body": ""},
                {"name": "no-desc", "description": "", "body": "b"},
                "not-a-dict",
            ]
        }
    )
    parsed = skills_mod._parse_distill_response(raw)
    assert [p["name"] for p in parsed] == ["ok"]


def _body_runner(body: str, name: str = "run-tests"):
    def runner(ctx, prompt: str) -> str:
        return json.dumps(
            {
                "skills": [
                    {
                        "name": name,
                        "description": "Run the project's test suite.",
                        "body": body,
                        "occurrences": 3,
                        "sources": ["2026-06-12.md"],
                    }
                ]
            }
        )

    return runner


def test_distill_evolves_existing_candidate_body(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)

    skills_mod.distill(
        platform="claude-code", project_dir=project, cfg=cfg, llm_runner=_body_runner("## v1\n\n1. pytest")
    )
    second = skills_mod.distill(
        platform="claude-code",
        project_dir=project,
        cfg=cfg,
        force=True,  # force, since the input journals are unchanged
        llm_runner=_body_runner("## v2\n\n1. pytest -x --ff"),
    )

    assert second.updated == ["run-tests"]
    assert second.created == []
    body = (project / ".memsearch" / "skill-candidates" / "run-tests" / "SKILL.md").read_text(encoding="utf-8")
    assert "pytest -x --ff" in body  # evolved in place


def test_installed_skill_source_keeps_evolving(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)

    skills_mod.distill(
        platform="claude-code", project_dir=project, cfg=cfg, llm_runner=_body_runner("## v1\n\n1. pytest")
    )
    skills_mod.install("run-tests", [str(project / ".claude" / "skills")], project_dir=project)

    # The store source keeps evolving even after install; the installed copy is a
    # snapshot that only changes on a later, deliberate re-install.
    result = skills_mod.distill(
        platform="claude-code",
        project_dir=project,
        cfg=cfg,
        force=True,
        llm_runner=_body_runner("## v2\n\n1. pytest -x --ff"),
    )

    assert result.updated == ["run-tests"]
    source = (project / ".memsearch" / "skill-candidates" / "run-tests" / "SKILL.md").read_text(encoding="utf-8")
    assert "pytest -x --ff" in source  # source evolved
    installed_copy = (project / ".claude" / "skills" / "run-tests" / "SKILL.md").read_text(encoding="utf-8")
    assert "pytest -x --ff" not in installed_copy  # snapshot unchanged until re-install
    listed = skills_mod.list_candidates(project / ".memsearch")
    assert listed[0]["pending_install"] is True
    assert listed[0]["pending_reason"] == "updated"
    assert listed[0]["installed_hash"] != listed[0]["content_hash"]


def test_candidate_review_summary_counts_pending_versions(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)

    skills_mod.distill(
        platform="claude-code",
        project_dir=project,
        cfg=cfg,
        llm_runner=_body_runner("## v1\n\n1. pytest", name="installed-skill"),
    )
    skills_mod.install("installed-skill", [str(project / ".claude" / "skills")], project_dir=project)
    skills_mod.distill(
        platform="claude-code",
        project_dir=project,
        cfg=cfg,
        force=True,
        llm_runner=_body_runner("## v2\n\n1. pytest -x --ff", name="installed-skill"),
    )
    skills_mod.add(
        "New Flow",
        "Capture a new flow. Use when asked to capture this flow.",
        "## New flow\n\n1. Do the thing",
        project_dir=project,
    )

    summary = skills_mod.candidate_review_summary(project / ".memsearch")

    assert summary["candidate_count"] == 2
    assert summary["pending_count"] == 2
    assert summary["new_count"] == 1
    assert summary["updated_count"] == 1
    assert summary["pending_names"] == ["installed-skill", "new-flow"]
    assert skills_mod.format_candidate_hint(summary).startswith("SKILLS: 2 candidate skill version(s) pending install")


def test_installed_candidate_with_legacy_meta_is_pending(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    skill_dir = project / ".memsearch" / "skill-candidates" / "legacy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: legacy\n---\n\n## Legacy\n", encoding="utf-8")
    (skill_dir / "meta.json").write_text(
        json.dumps(
            {
                "name": "legacy",
                "status": "installed",
                "description": "Legacy installed skill.",
                "installed_paths": [str(project / ".agents" / "skills" / "legacy" / "SKILL.md")],
            }
        ),
        encoding="utf-8",
    )

    listed = skills_mod.list_candidates(project / ".memsearch")

    assert listed[0]["content_hash"].startswith("gitblob:")
    assert listed[0]["pending_install"] is True
    assert listed[0]["pending_reason"] == "updated"


def test_cli_skills_status_outputs_hint(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from memsearch.cli import cli

    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.chdir(project)
    skills_mod.add(
        "Review Me",
        "Review this candidate. Use when testing skill status.",
        "## Review\n\n1. Check it",
        project_dir=project,
    )

    result = CliRunner().invoke(cli, ["skills", "status", "--hint"])

    assert result.exit_code == 0
    assert "SKILLS: 1 candidate skill version(s) pending install" in result.output


def test_load_template_respects_custom_prompt(tmp_path: Path) -> None:
    custom = tmp_path / "my_distill.txt"
    custom.write_text("CUSTOM DISTILL TEMPLATE {{MIN_OCCURRENCES}}", encoding="utf-8")
    cfg = MemSearchConfig()
    cfg.prompts.memory_to_skill = str(custom)

    assert skills_mod._load_template(cfg).startswith("CUSTOM DISTILL TEMPLATE")
    # Falls back to the packaged default when no override is configured.
    assert "distilling reusable skills" in skills_mod._load_template()


def test_config_set_paths_parses_json_list(tmp_path: Path, monkeypatch) -> None:
    from memsearch.config import GLOBAL_CONFIG_PATH, load_config_file, set_config_value

    monkeypatch.chdir(tmp_path)
    set_config_value(
        "plugins.claude-code.memory_to_skill.paths",
        '[".claude/skills", "~/.codex/skills"]',
    )
    data = load_config_file(GLOBAL_CONFIG_PATH)
    assert data["plugins"]["claude-code"]["memory_to_skill"]["paths"] == [".claude/skills", "~/.codex/skills"]


def test_add_persists_candidate_without_llm(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    slug = skills_mod.add(
        "My Deploy Flow", "Deploy to staging. Use when asked to deploy.", "## Deploy\n\n1. push", project_dir=project
    )

    assert slug == "my-deploy-flow"
    skill_dir = project / ".memsearch" / "skill-candidates" / "my-deploy-flow"
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: my-deploy-flow\n")
    meta = json.loads((skill_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "candidate"
    assert (project / ".memsearch" / "skill-candidates" / ".git").is_dir()


def test_add_rejects_empty_body(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="description and a body"):
        skills_mod.add("x", "desc", "   ", project_dir=tmp_path)


def test_distill_runs_when_disabled_if_require_enabled_false(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()  # memory_to_skill disabled by default

    result = skills_mod.distill(
        platform="claude-code", project_dir=project, cfg=cfg, require_enabled=False, llm_runner=_one_skill_runner()
    )

    assert result.action == "distilled"
    assert result.created == ["run-tests"]


def test_distill_honors_custom_input_dir(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)  # default location, with different content
    custom = tmp_path / "journals"
    custom.mkdir()
    (custom / "2026-06-13.md").write_text("### 11:00\n- CUSTOM-INPUT-DIR marker.\n", encoding="utf-8")

    cfg = MemSearchConfig()
    _enable(cfg)
    cfg.plugins.claude_code.memory_to_skill.input_dir = str(custom)

    captured = {}

    def runner(ctx, prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps({"skills": []})

    skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, llm_runner=runner)
    assert "CUSTOM-INPUT-DIR marker" in captured["prompt"]


def test_revision_prompt_includes_current_body(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    cfg = MemSearchConfig()
    _enable(cfg)

    skills_mod.distill(
        platform="claude-code",
        project_dir=project,
        cfg=cfg,
        llm_runner=_body_runner("## v1 body\n\n1. UNIQUE-OLD-STEP"),
    )

    captured = {}

    def checking_runner(ctx, prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps({"skills": []})

    skills_mod.distill(platform="claude-code", project_dir=project, cfg=cfg, force=True, llm_runner=checking_runner)
    # The model must see the current body when revising, not just name/description.
    assert "UNIQUE-OLD-STEP" in captured["prompt"]


def test_cli_distill_native_gives_guidance_not_crash(monkeypatch) -> None:
    from click.testing import CliRunner

    from memsearch import cli as cli_module
    from memsearch.cli import cli

    # Default config => native provider; standalone CLI distill cannot run native.
    monkeypatch.setattr(cli_module, "resolve_config", lambda *_a, **_k: MemSearchConfig())
    result = CliRunner().invoke(cli, ["skills", "distill", "--plugin", "codex"])

    assert result.exit_code == 2
    assert "needs an API provider" in result.stderr
    assert "Native maintenance providers" not in (result.stderr + result.output)  # no raw traceback


def _write_failed_maintenance_state(project: Path) -> None:
    mem_root = project / ".memsearch"
    mem_root.mkdir(parents=True, exist_ok=True)
    state_path = mem_root / ".maintenance-state.json"
    state_path.write_text(
        json.dumps(
            {
                "codex.project_review": {
                    "last_action": "error",
                    "last_checked_at": "2026-11-08T00:00:00+00:00",
                    "last_failed_at": "2026-11-08T00:30:00+00:00",
                    "last_error": "RuntimeError: provider timeout",
                }
            }
        ),
        encoding="utf-8",
    )
    return mem_root


def test_last_maintenance_status_reads_failure(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    mem_root = _write_failed_maintenance_state(project)

    status = skills_mod.last_maintenance_status(mem_root)

    assert status["task"] == "codex.project_review"  # the state key names the task
    assert status["last_action"] == "error"
    assert status["last_failed_at"] == "2026-11-08T00:30:00+00:00"
    assert "provider timeout" in status["last_error"]


def test_last_maintenance_status_picks_the_most_recent_task(tmp_path: Path) -> None:
    """With several task entries, the latest last_checked_at wins, key as task."""
    project = tmp_path / "repo"
    mem_root = project / ".memsearch"
    mem_root.mkdir(parents=True)
    (mem_root / ".maintenance-state.json").write_text(
        json.dumps(
            {
                "codex.memory_to_skill": {
                    "last_action": "replace",
                    "last_checked_at": "2026-11-08T01:00:00+00:00",
                    "last_success_at": "2026-11-08T01:00:00+00:00",
                },
                "codex.project_review": {
                    "last_action": "error",
                    "last_checked_at": "2026-11-08T02:00:00+00:00",
                    "last_failed_at": "2026-11-08T02:00:00+00:00",
                    "last_error": "RuntimeError: newer task failed",
                },
                "codex.user_profile": {
                    "last_action": "error",
                    "last_checked_at": "2026-11-08T00:30:00+00:00",
                    "last_failed_at": "2026-11-08T00:30:00+00:00",
                    "last_error": "RuntimeError: older task failed",
                },
            }
        ),
        encoding="utf-8",
    )

    status = skills_mod.last_maintenance_status(mem_root)

    assert status["task"] == "codex.project_review"
    assert status["last_action"] == "error"
    assert "newer task failed" in status["last_error"]


def test_last_maintenance_status_missing_or_broken_state_is_empty(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    mem_root = project / ".memsearch"
    mem_root.mkdir(parents=True)

    assert skills_mod.last_maintenance_status(mem_root) == {}

    (mem_root / ".maintenance-state.json").write_text("{not json", encoding="utf-8")
    assert skills_mod.last_maintenance_status(mem_root) == {}


def test_candidate_review_summary_includes_last_maintenance(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_memory(project)
    skills_mod.add(
        "Review Me",
        "Review this candidate. Use when testing summaries.",
        "## Review\n\n1. Check it",
        project_dir=project,
    )
    mem_root = _write_failed_maintenance_state(project)

    summary = skills_mod.candidate_review_summary(mem_root)

    assert summary["last_maintenance"]["last_action"] == "error"


def test_cli_skills_status_reports_maintenance_failure(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from memsearch.cli import cli

    project = tmp_path / "repo"
    project.mkdir()
    monkeypatch.chdir(project)
    _write_failed_maintenance_state(project)

    result = CliRunner().invoke(cli, ["skills", "status"])

    assert result.exit_code == 0
    assert "Last maintenance run failed (2026-11-08T00:30:00+00:00):" in result.output
    assert "RuntimeError: provider timeout" in result.output
    assert ".memsearch/.maintenance-state.json" in result.output
