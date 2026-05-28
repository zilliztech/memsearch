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


def ensure_opencode_isolated_config() -> Path:
    home = Path.home()
    isolated = home / ".codex" / "tmp" / "opencode-memsearch-maintenance" / "opencode"
    isolated.mkdir(parents=True, exist_ok=True)
    src = home / ".config" / "opencode" / "opencode.json"
    if src.is_file():
        shutil.copy2(src, isolated / "opencode.json")
    return isolated


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
    for task in ("project_review", "user_profile"):
        if getattr(cfg.prompts, task, ""):
            continue
        prompt_file = prompts_dir / f"{task}.txt"
        if prompt_file.is_file():
            setattr(cfg.prompts, task, str(prompt_file))


def run_native_provider(ctx, prompt: str) -> str:
    model = ctx.task_config.model or DEFAULT_NATIVE_MODELS.get(ctx.platform, "")
    env = {**os.environ, "MEMSEARCH_NO_WATCH": "1"}

    if ctx.platform == "claude-code":
        cmd = ["claude", "-p", "--strict-mcp-config", "--no-session-persistence", "--no-chrome"]
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
        with tempfile.NamedTemporaryFile(prefix="memsearch-codex-maintenance-", suffix=".txt", delete=False) as output_file:
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
        isolated = ensure_opencode_isolated_config()
        cmd = ["opencode", "run"]
        if model:
            cmd += ["-m", model]
        cmd.append(prompt)
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
    except (KeyError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"Maintenance error: {exc}\n")
        return 1
    finally:
        with contextlib.suppress(OSError):
            os.chdir(old_cwd)

    payload = [result.__dict__ for result in results]
    if args.json_output:
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        for result in results:
            detail = f": {result.reason}" if result.reason else ""
            sys.stdout.write(f"{result.task}: {result.action}{detail}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
