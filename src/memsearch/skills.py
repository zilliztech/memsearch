"""Memory-to-skill distillation.

Distills recurring multi-step workflows from recent memory journals into
*candidate* skills under ``.memsearch/skill-candidates/``.  Candidates are
inert: they are never written into an agent's skills directory by this module.
Turning a candidate into an agent-visible skill is a separate, human-driven
step (:func:`install`, surfaced by the ``/memory-to-skill`` skill).

The candidate store is a self-contained git repository at
``.memsearch/skill-candidates/`` so every automatic edit is a commit with full
history, diff, and revert — the agent (or a human) can trace which change broke
a skill and roll it back.

This is procedural memory: the third layer alongside the episodic daily
journals and the semantic ``PROJECT.md`` / ``USER.md`` files.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from .config import MemSearchConfig, PluginMemoryToSkillConfig, config_to_dict
from .maintenance import (
    MAX_PROMPT_CHARS,
    TaskContext,
    _file_lock,
    _input_digest,
    _is_due,
    _load_state,
    _read_recent_journals,
    _resolve_task_path,
    _save_state,
    run_task_llm,
)

# Cap each existing skill body included in the revision prompt, to bound size.
MAX_EXISTING_BODY_CHARS = 2000

TASK = "memory_to_skill"
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


@dataclass
class DistillResult:
    action: str  # "distilled" | "none" | "skip" | "disabled" | "locked"
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    reason: str = ""
    skipped: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_roots(project_dir: str | Path | None, memsearch_dir: str | Path | None) -> tuple[Path, Path]:
    project_root = Path(project_dir or os.getcwd()).expanduser().resolve()
    mem_root = Path(memsearch_dir or os.environ.get("MEMSEARCH_DIR", project_root / ".memsearch")).expanduser()
    if not mem_root.is_absolute():
        mem_root = project_root / mem_root
    return project_root, mem_root.resolve()


def skills_root(mem_root: Path) -> Path:
    """Path to the candidate skill store inside a ``.memsearch`` directory.

    Named ``skill-candidates`` (not ``skills``) so a human browsing the project
    does not mistake these evolving drafts for the live, installed skills under
    ``.claude/skills`` / ``.codex/skills`` / ``.agents/skills``.
    """
    return mem_root / "skill-candidates"


def _get_task_config(cfg: MemSearchConfig, platform: str) -> PluginMemoryToSkillConfig | None:
    plugins = config_to_dict(cfg).get("plugins", {})
    platform_cfg = plugins.get(platform)
    if not isinstance(platform_cfg, dict):
        return None
    task_data = platform_cfg.get(TASK)
    if not isinstance(task_data, dict):
        return None
    return PluginMemoryToSkillConfig(
        **{k: v for k, v in task_data.items() if k in PluginMemoryToSkillConfig.__dataclass_fields__}
    )


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "skill"


def _skill_body(skill_md: str) -> str:
    """Return the markdown body of a SKILL.md, stripping YAML frontmatter."""
    if skill_md.startswith("---"):
        parts = skill_md.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return skill_md.strip()


def _render_existing_block(root: Path, existing: list[dict[str, Any]]) -> str:
    """Render existing skills with their current bodies, so revisions improve
    the current version rather than rewriting it blindly from recent logs."""
    if not existing:
        return "(none)"
    blocks: list[str] = []
    for m in existing:
        name = m.get("name", "")
        desc = m.get("description", "")
        body = ""
        skill_md = root / str(name) / "SKILL.md"
        if skill_md.is_file():
            body = _skill_body(skill_md.read_text(encoding="utf-8"))
            if len(body) > MAX_EXISTING_BODY_CHARS:
                body = body[:MAX_EXISTING_BODY_CHARS] + "\n…[truncated]"
        blocks.append(f"### {name}\n{desc}\n\nCurrent body:\n```markdown\n{body}\n```")
    return "\n\n".join(blocks)


def _load_template(cfg: MemSearchConfig | None = None) -> str:
    # User/plugin override first (same mechanism as project_review / user_profile),
    # then the packaged default.
    configured = getattr(cfg.prompts, TASK, "") if cfg is not None else ""
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8")
    with resources.files("memsearch.prompts").joinpath(f"{TASK}.txt").open("r", encoding="utf-8") as f:
        return f.read()


def _build_distill_prompt(
    ctx: TaskContext, *, min_occurrences: int, existing: list[dict[str, Any]], cfg: MemSearchConfig | None = None
) -> str:
    template = _load_template(cfg)
    for marker, value in {
        "{{AGENT_NAME}}": ctx.platform,
        "{{PROJECT_DIR}}": str(ctx.project_dir),
        "{{INPUT_DIR}}": str(ctx.input_dir),
        "{{MIN_OCCURRENCES}}": str(min_occurrences),
    }.items():
        template = template.replace(marker, value)

    existing_block = _render_existing_block(skills_root(ctx.memsearch_dir), existing)
    journals = _read_recent_journals(ctx.input_dir)
    prompt = f"""{template}

## Existing skills (you may revise these)

{existing_block}

## Recent memory journal entries

```markdown
{journals.strip()}
```
"""
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n\n[truncated]\n"
    return prompt


def _parse_distill_response(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"memory_to_skill LLM did not return valid JSON: {e}") from e
    skills = data.get("skills")
    if not isinstance(skills, list):
        raise RuntimeError("memory_to_skill response must contain a 'skills' list")
    cleaned: list[dict[str, Any]] = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        name = _slugify(str(item.get("name", "")))
        description = str(item.get("description", "")).strip()
        body = str(item.get("body", "")).strip()
        if not description or not body:
            continue
        cleaned.append(
            {
                "name": name,
                "description": description,
                "body": body,
                "occurrences": item.get("occurrences"),
                "sources": item.get("sources") or [],
                "reason": str(item.get("reason", "")).strip(),
            }
        )
    return cleaned


def _render_skill_md(name: str, description: str, body: str) -> str:
    # Only standard, cross-platform fields (agentskills.io). Tracking metadata
    # lives in meta.json, never in frontmatter.
    return f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n{body.rstrip()}\n"


# ---- git-backed candidate store -------------------------------------------------


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=memsearch",
            "-c",
            "user.email=memsearch@localhost",
            *args,
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )


def _ensure_git(root: Path) -> None:
    if (root / ".git").exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")


def _git_commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    status = _git(root, "status", "--porcelain")
    if not status.stdout.strip():
        return  # nothing staged; avoid empty commits
    _git(root, "commit", "-q", "-m", message)


def list_candidates(mem_root: Path) -> list[dict[str, Any]]:
    """Return metadata for every skill in the candidate store."""
    root = skills_root(mem_root)
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for child in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        meta_path = child / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(meta)
    return out


def _write_candidate(root: Path, skill: dict[str, Any]) -> str:
    """Write or evolve one candidate.

    Returns ``"created"`` for a new candidate dir, or ``"updated"`` when an
    existing entry's body is refreshed.

    Every entry in the store keeps evolving in the background, including ones
    already installed — the store is the perpetually-updated source. Installing
    only ever takes a snapshot out (a deliberate, human-driven step); it never
    freezes the source here.
    """
    name = skill["name"]
    skill_dir = root / name
    meta_path = skill_dir / "meta.json"
    sources = list(skill.get("sources") or [])

    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
        meta["sources"] = sorted(set(meta.get("sources", [])) | set(sources))
        if isinstance(skill.get("occurrences"), int):
            meta["occurrences"] = max(int(meta.get("occurrences", 0) or 0), skill["occurrences"])
        meta["description"] = skill["description"]
        meta["updated_at"] = _now()
        (skill_dir / "SKILL.md").write_text(
            _render_skill_md(name, skill["description"], skill["body"]), encoding="utf-8"
        )
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return "updated"

    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_render_skill_md(name, skill["description"], skill["body"]), encoding="utf-8")
    now = _now()
    meta = {
        "name": name,
        "status": "candidate",
        "description": skill["description"],
        "occurrences": skill.get("occurrences"),
        "sources": sources,
        "reason": skill.get("reason", ""),
        "installed_paths": [],
        "created_at": now,
        "updated_at": now,
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return "created"


def distill(
    *,
    platform: str,
    project_dir: str | Path | None = None,
    memsearch_dir: str | Path | None = None,
    cfg: MemSearchConfig | None = None,
    force: bool = False,
    require_enabled: bool = True,
    llm_runner: Callable[[TaskContext, str], str] | None = None,
) -> DistillResult:
    """Distill candidate skills from recent journals if the task is due.

    *require_enabled* controls whether the ``enabled`` flag gates this run. The
    session-end background runner passes ``True`` (so disabling the task stops
    surprise background calls); an explicit CLI invocation passes ``False``,
    since an explicit request is never a surprise.
    """
    if cfg is None:
        from .config import resolve_config

        cfg = resolve_config()

    task_cfg = _get_task_config(cfg, platform) or PluginMemoryToSkillConfig()
    if require_enabled and not task_cfg.enabled:
        return DistillResult(action="disabled", skipped=True)

    project_root, mem_root = resolve_roots(project_dir, memsearch_dir)
    mem_root.mkdir(parents=True, exist_ok=True)
    input_dir = _resolve_task_path(task_cfg.input_dir or str(mem_root / "memory"), project_root, mem_root)

    state_path = mem_root / ".maintenance-state.json"
    state = _load_state(state_path)
    state_key = f"{platform}.{TASK}"
    digest = _input_digest(input_dir)
    due, reason = _is_due(task_cfg, state.get(state_key, {}), digest, force)
    if not due:
        return DistillResult(action="skip", reason=reason, skipped=True)

    lock_path = mem_root / f".maintenance-{platform}-{TASK}.lock"
    with _file_lock(lock_path) as locked:
        if not locked:
            return DistillResult(action="locked", skipped=True)

        root = skills_root(mem_root)
        _ensure_git(root)

        ctx = TaskContext(
            platform=platform,
            task=TASK,
            task_config=task_cfg,  # type: ignore[arg-type]
            project_dir=project_root,
            memsearch_dir=mem_root,
            input_dir=input_dir,
            output_file=root,
            input_digest=digest,
        )
        prompt = _build_distill_prompt(
            ctx, min_occurrences=task_cfg.min_occurrences, existing=list_candidates(mem_root), cfg=cfg
        )
        raw = llm_runner(ctx, prompt) if llm_runner else run_task_llm(ctx, prompt, cfg)
        candidates = _parse_distill_response(raw)

        created: list[str] = []
        updated: list[str] = []
        for skill in candidates:
            outcome = _write_candidate(root, skill)
            if outcome == "created":
                created.append(skill["name"])
            elif outcome == "updated":
                updated.append(skill["name"])

        changed = bool(created or updated)
        if changed:
            parts = []
            if created:
                parts.append(f"add {len(created)}")
            if updated:
                parts.append(f"evolve {len(updated)}")
            _git_commit(root, f"distill: {', '.join(parts)} candidate skill(s) [{platform}]")
        else:
            _git_commit(root, f"distill: refresh candidate metadata [{platform}]")

        now = _now()
        state[state_key] = {
            "last_checked_at": now,
            "last_success_at": now,
            "last_input_digest": digest,
            "last_action": "distilled" if changed else "none",
            "output_file": str(root),
        }
        _save_state(state_path, state)

    return DistillResult(action="distilled" if changed else "none", created=created, updated=updated)


def add(
    name: str,
    description: str,
    body: str,
    *,
    project_dir: str | Path | None = None,
    memsearch_dir: str | Path | None = None,
) -> str:
    """Persist a caller-provided skill as a candidate (manual capture path).

    Used when a live agent has already drafted a skill from what the user just
    did — the agent supplies the content and this only handles slugging,
    standard frontmatter, the meta.json schema, and the git commit, so a
    manually captured candidate is structurally identical to a distilled one.
    Returns the slugified candidate name. No LLM and no provider config needed.
    """
    if not description.strip() or not body.strip():
        raise ValueError("a skill needs both a description and a body")

    _project_root, mem_root = resolve_roots(project_dir, memsearch_dir)
    root = skills_root(mem_root)
    _ensure_git(root)
    slug = _slugify(name)
    outcome = _write_candidate(
        root,
        {"name": slug, "description": description.strip(), "body": body.strip(), "sources": [], "reason": "manual"},
    )
    _git_commit(root, f"add: {outcome} candidate skill {slug} (manual)")
    return slug


def install(
    name: str,
    paths: list[str],
    *,
    project_dir: str | Path | None = None,
    memsearch_dir: str | Path | None = None,
) -> list[str]:
    """Snapshot a candidate skill into one or more agent skill directories.

    Copies the candidate's current ``SKILL.md`` to each destination and marks it
    ``installed`` in the store. The store copy keeps evolving afterwards; a later
    install takes a fresh snapshot. Returns the installed destinations. Raises
    ``ValueError`` if the candidate is missing or *paths* is empty.
    """
    if not paths:
        raise ValueError("no install paths given; ask the user where to install the skill")

    project_root, mem_root = resolve_roots(project_dir, memsearch_dir)
    root = skills_root(mem_root)
    skill_dir = root / _slugify(name)
    src = skill_dir / "SKILL.md"
    if not src.is_file():
        raise ValueError(f"no candidate skill named {name!r}")

    skill_md = src.read_text(encoding="utf-8")
    installed: list[str] = []
    for raw_path in paths:
        base = Path(raw_path).expanduser()
        if not base.is_absolute():
            base = project_root / base
        dest_dir = base / skill_dir.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "SKILL.md"
        dest.write_text(skill_md, encoding="utf-8")
        installed.append(str(dest))

    meta_path = skill_dir / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
        meta["status"] = "installed"
        meta["installed_paths"] = sorted(set(meta.get("installed_paths", [])) | set(installed))
        meta["updated_at"] = _now()
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _git_commit(root, f"install: {skill_dir.name} -> {len(installed)} path(s)")

    return installed
