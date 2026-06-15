#!/usr/bin/env python3
"""Plugin-local runner for MemSearch maintenance tasks.

This script belongs to the plugin layer. It handles host-native agent
invocations, while the Python package provides shared config, due-state,
prompt, and API-provider logic.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_NATIVE_MODELS = {
    "claude-code": "sonnet",
    "codex": "",
    "opencode": "",
    "openclaw": "",
}


def _strip_jsonc(text: str) -> str:
    """Remove JSONC comments and trailing commas while preserving string contents."""
    out: list[str] = []
    i = 0
    in_string = False
    string_quote = ""
    escaped = False
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            out.append(char)
            i += 1
            continue
        if char == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1

    without_comments = "".join(out)
    out = []
    i = 0
    in_string = False
    string_quote = ""
    escaped = False
    while i < len(without_comments):
        char = without_comments[i]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            out.append(char)
            i += 1
            continue
        if char == ",":
            j = i + 1
            while j < len(without_comments) and without_comments[j].isspace():
                j += 1
            if j < len(without_comments) and without_comments[j] in "]}":
                i += 1
                continue
        out.append(char)
        i += 1
    return "".join(out)


def _read_jsonc_config_from_text(text: str) -> dict:
    try:
        data = json.loads(_strip_jsonc(text))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonc_config(path: Path) -> dict:
    try:
        return _read_jsonc_config_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _deep_merge_config(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_config(result[key], value)
        else:
            result[key] = value
    return result


def _rewrite_relative_file_refs(value, config_dir: Path):
    if isinstance(value, dict):
        return {key: _rewrite_relative_file_refs(item, config_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_relative_file_refs(item, config_dir) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        file_ref = match.group(1)
        if file_ref.startswith("~/") or os.path.isabs(file_ref):
            return match.group(0)
        return "{file:" + str((config_dir / file_ref).resolve()) + "}"

    return re.sub(r"\{file:([^}]+)\}", replace, value)


def _load_opencode_config_file(path: Path) -> dict:
    cfg = _read_jsonc_config(path)
    if not cfg:
        return {}
    return _rewrite_relative_file_refs(cfg, path.parent)


def _opencode_global_config_dir() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config).expanduser() / "opencode"
    return Path.home() / ".config" / "opencode"


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _opencode_project_config_files(project_dir: Path) -> list[Path]:
    found: list[Path] = []
    current = project_dir.resolve()
    while True:
        for filename in ("opencode.jsonc", "opencode.json"):
            candidate = current / filename
            if candidate.is_file():
                found.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return list(reversed(found))


def _opencode_directory_config_files(project_dir: Path) -> list[Path]:
    dirs: list[Path] = []
    if not _env_flag_enabled("OPENCODE_DISABLE_PROJECT_CONFIG"):
        current = project_dir.resolve()
        while True:
            local = current / ".opencode"
            if local.is_dir() and local not in dirs:
                dirs.append(local)
            parent = current.parent
            if parent == current:
                break
            current = parent

    home_local = Path.home() / ".opencode"
    if home_local.is_dir() and home_local not in dirs:
        dirs.append(home_local)

    env_dir = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if env_dir:
        config_dir = Path(env_dir).expanduser()
        if config_dir not in dirs:
            dirs.append(config_dir)

    files: list[Path] = []
    for directory in dirs:
        for filename in ("opencode.json", "opencode.jsonc"):
            candidate = directory / filename
            if candidate.is_file():
                files.append(candidate)
    return files


def _iter_opencode_config_files(project_dir: str | os.PathLike[str] | None = None) -> list[Path]:
    project = Path(project_dir or os.getcwd()).expanduser().resolve()
    files: list[Path] = []

    global_dir = _opencode_global_config_dir()
    for filename in ("config.json", "opencode.json", "opencode.jsonc"):
        candidate = global_dir / filename
        if candidate.is_file():
            files.append(candidate)

    env_config = os.environ.get("OPENCODE_CONFIG", "").strip()
    if env_config:
        candidate = Path(env_config).expanduser()
        if candidate.is_file():
            files.append(candidate)

    if not _env_flag_enabled("OPENCODE_DISABLE_PROJECT_CONFIG"):
        files.extend(_opencode_project_config_files(project))

    files.extend(_opencode_directory_config_files(project))
    return files


def load_opencode_config(project_dir: str | os.PathLike[str] | None = None) -> dict:
    """Load local OpenCode config sources in OpenCode-compatible precedence order."""
    merged: dict = {}
    for path in _iter_opencode_config_files(project_dir):
        merged = _deep_merge_config(merged, _load_opencode_config_file(path))

    content = os.environ.get("OPENCODE_CONFIG_CONTENT")
    if content:
        content_dir = Path(project_dir or os.getcwd()).expanduser().resolve()
        cfg = _rewrite_relative_file_refs(_read_jsonc_config_from_text(content), content_dir)
        merged = _deep_merge_config(merged, cfg)
    return merged


def _sanitize_opencode_config(cfg: dict) -> dict:
    sanitized = dict(cfg)
    for key in ("plugin", "plugins", "plugin_origins"):
        sanitized.pop(key, None)
    return sanitized


def run_command(cmd: list[str], *, env: dict[str, str], cwd: Path, timeout: int) -> str:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=timeout,
        check=False,
    )
    return (result.stdout or result.stderr or "").strip()


def extract_task_json_output(output: str) -> str:
    """Extract the first maintenance JSON object from noisy host output."""
    for line in output.splitlines():
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "action" in parsed:
            return json.dumps(parsed, ensure_ascii=False)
    return output


def ensure_opencode_isolated_config(project_dir: str | os.PathLike[str] | None = None) -> Path:
    home = Path.home()
    root = home / ".codex" / "tmp" / "opencode-memsearch-maintenance"
    isolated = root / "opencode"
    isolated.mkdir(parents=True, exist_ok=True)
    for filename in ("config.json", "opencode.json", "opencode.jsonc"):
        stale = isolated / filename
        if stale.is_symlink() or stale.is_file():
            stale.unlink(missing_ok=True)
    cfg = _sanitize_opencode_config(load_opencode_config(project_dir))
    if cfg:
        (isolated / "opencode.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return root


def ensure_memsearch_importable() -> None:
    user_paths = [
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".cargo" / "bin"),
        str(Path.home() / "bin"),
        "/usr/local/bin",
    ]
    existing_path = os.environ.get("PATH", "")
    path_parts = existing_path.split(os.pathsep) if existing_path else []
    for user_path in reversed(user_paths):
        if Path(user_path).is_dir() and user_path not in path_parts:
            path_parts.insert(0, user_path)
    os.environ["PATH"] = os.pathsep.join(path_parts)

    for parent in Path(__file__).resolve().parents:
        src_dir = parent / "src"
        if (src_dir / "memsearch").is_dir():
            sys.path.insert(0, str(src_dir))
            break

    try:
        import memsearch  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    if os.environ.get("MEMSEARCH_MAINTENANCE_UV_BOOTSTRAP") == "1":
        return

    memsearch_bin = shutil.which("memsearch")
    if memsearch_bin:
        with contextlib.suppress(OSError, UnicodeDecodeError):
            first_line = Path(memsearch_bin).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            if first_line.startswith("#!"):
                python_bin = first_line[2:].strip().split()[0]
                if python_bin:
                    os.execvpe(
                        python_bin,
                        [python_bin, str(Path(__file__).resolve()), *sys.argv[1:]],
                        {**os.environ, "MEMSEARCH_MAINTENANCE_UV_BOOTSTRAP": "1"},
                    )

    uv = shutil.which("uv")
    if not uv:
        return

    env = {**os.environ, "MEMSEARCH_MAINTENANCE_UV_BOOTSTRAP": "1"}
    os.execvpe(
        uv,
        [
            uv,
            "run",
            "--with",
            "memsearch[onnx]",
            "python",
            str(Path(__file__).resolve()),
            *sys.argv[1:],
        ],
        env,
    )


def apply_plugin_prompt_defaults(cfg) -> None:
    plugin_dir = Path(__file__).resolve().parent.parent
    prompts_dir = plugin_dir / "prompts"
    for task in ("project_review", "user_profile", "memory_to_skill"):
        if getattr(cfg.prompts, task, ""):
            continue
        prompt_file = prompts_dir / f"{task}.txt"
        if prompt_file.is_file():
            setattr(cfg.prompts, task, str(prompt_file))


def run_native_provider(ctx, prompt: str) -> str:
    model = ctx.task_config.model or DEFAULT_NATIVE_MODELS.get(ctx.platform, "")
    env = {**os.environ, "MEMSEARCH_NO_WATCH": "1"}

    if ctx.platform == "claude-code":
        cmd = ["claude", "-p", "--strict-mcp-config", "--tools", "", "--no-session-persistence", "--no-chrome"]
        if model:
            cmd += ["--model", model]
        cmd += [
            "--system-prompt",
            "You are a maintenance task runner. Output only the requested JSON object.",
            prompt,
        ]
        env["CLAUDECODE"] = ""
        return run_command(cmd, env=env, cwd=ctx.project_dir, timeout=120)

    if ctx.platform == "codex":
        with tempfile.NamedTemporaryFile(
            prefix="memsearch-codex-maintenance-", suffix=".txt", delete=False
        ) as output_file:
            output_path = Path(output_file.name)
        cmd = [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "-s",
            "read-only",
            "-c",
            "features.hooks=false",
            "-c",
            'model_reasoning_effort="medium"',
            "-o",
            str(output_path),
        ]
        profile = os.environ.get("MEMSEARCH_CODEX_PROFILE", "").strip()
        if profile:
            cmd += ["-p", profile]
        if model:
            cmd += ["-m", model]
        cmd.append(prompt)
        env["MEMSEARCH_IN_STOP_WORKER"] = "1"
        try:
            run_command(cmd, env=env, cwd=ctx.project_dir, timeout=120)
            return output_path.read_text(encoding="utf-8", errors="replace").strip()
        finally:
            output_path.unlink(missing_ok=True)

    if ctx.platform == "openclaw":
        cmd = ["openclaw", "agent", "--local", "--session-id", "memsearch-maintenance"]
        if model:
            cmd += ["--model", model]
        cmd += ["-m", prompt]
        env["MEMSEARCH_DISABLE"] = "1"
        return extract_task_json_output(run_command(cmd, env=env, cwd=ctx.project_dir, timeout=120))

    if ctx.platform == "opencode":
        isolated = ensure_opencode_isolated_config(ctx.project_dir)
        cmd = ["opencode", "run"]
        if model:
            cmd += ["-m", model]
        cmd.append(prompt)
        env["OPENCODE_CONFIG"] = ""
        env["OPENCODE_CONFIG_DIR"] = ""
        env["OPENCODE_CONFIG_CONTENT"] = ""
        env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "true"
        env["XDG_CONFIG_HOME"] = str(isolated)
        env["XDG_DATA_HOME"] = str(isolated / "data")
        return run_command(cmd, env=env, cwd=ctx.project_dir, timeout=120)

    raise RuntimeError(f"Unsupported native maintenance platform {ctx.platform!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run plugin-local MemSearch maintenance tasks.")
    parser.add_argument("--platform", required=True, choices=["claude-code", "codex", "opencode", "openclaw"])
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--memsearch-dir", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()

    old_cwd = Path.cwd()
    try:
        ensure_memsearch_importable()
        from memsearch.config import resolve_config
        from memsearch.maintenance import run_due_tasks, run_task_llm

        project_dir = Path(args.project_dir or old_cwd).expanduser().resolve()
        os.chdir(project_dir)
        cfg = resolve_config()
        apply_plugin_prompt_defaults(cfg)

        def llm_runner(ctx, prompt: str) -> str:
            provider_name = (ctx.task_config.provider or "native").strip()
            if provider_name in {"", "native"}:
                return run_native_provider(ctx, prompt)
            return run_task_llm(ctx, prompt, cfg)

        results = run_due_tasks(
            platform=args.platform,
            project_dir=project_dir,
            memsearch_dir=args.memsearch_dir,
            cfg=cfg,
            force=args.force,
            llm_runner=llm_runner,
        )

        # Distill recurring workflows into candidate skills (procedural memory).
        # Same session-end trigger, due-state, and llm_runner as the tasks above;
        # this only ever touches the candidate store, never an agent's skills dir.
        from memsearch.skills import distill as distill_skills

        skill_result = distill_skills(
            platform=args.platform,
            project_dir=project_dir,
            memsearch_dir=args.memsearch_dir,
            cfg=cfg,
            force=args.force,
            llm_runner=llm_runner,
        )
    except (KeyError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"Maintenance error: {exc}\n")
        return 1
    finally:
        with contextlib.suppress(OSError):
            os.chdir(old_cwd)

    payload = [result.__dict__ for result in results]
    payload.append({"task": "memory_to_skill", **skill_result.__dict__})
    if args.json_output:
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        for result in results:
            detail = f": {result.reason}" if result.reason else ""
            sys.stdout.write(f"{result.task}: {result.action}{detail}\n")
        skill_detail = f": {skill_result.reason}" if skill_result.reason else ""
        sys.stdout.write(f"memory_to_skill: {skill_result.action}{skill_detail}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
