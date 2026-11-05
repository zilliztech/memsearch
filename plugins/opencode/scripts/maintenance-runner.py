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
import shlex
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
    "dsh": "",  # dsh-headless uses the user's agent-default-model from settings.yaml
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
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = "\n".join(part for part in (stdout, stderr) if part)
        if len(detail) > 2000:
            detail = detail[:1975] + "... [truncated]"
        command = " ".join(shlex.quote(_describe_arg(part)) for part in cmd)
        if len(command) > 300:
            command = command[:275] + "... [truncated]"
        message = f"Command failed ({result.returncode}): {command}"
        if detail:
            message = f"{message}\n{detail}"
        raise RuntimeError(message)
    return stdout or stderr


def _describe_arg(arg: str, limit: int = 120) -> str:
    if len(arg) <= limit:
        return arg
    return f"<arg:{len(arg)} chars>"


_CLAUDE_SAFE_MODE_ARGS: list[str] | None = None


def claude_safe_mode_args() -> list[str]:
    """Return Claude args that suppress hooks when supported."""
    global _CLAUDE_SAFE_MODE_ARGS
    if _CLAUDE_SAFE_MODE_ARGS is not None:
        return _CLAUDE_SAFE_MODE_ARGS
    try:
        result = subprocess.run(
            ["claude", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _CLAUDE_SAFE_MODE_ARGS = []
    else:
        help_text = f"{result.stdout}\n{result.stderr}"
        _CLAUDE_SAFE_MODE_ARGS = ["--safe-mode"] if "--safe-mode" in help_text else []
    return _CLAUDE_SAFE_MODE_ARGS


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


def _reexec(argv: list[str], env: dict[str, str]) -> None:
    """Windows exec launches a child; wait and propagate its actual exit status."""
    if os.name == "nt":
        raise SystemExit(subprocess.run(argv, env=env, check=False).returncode)
    os.execvpe(argv[0], argv, env)


def ensure_memsearch_importable(entrypoint: Path | None = None) -> None:
    entrypoint = entrypoint or Path(__file__).resolve()
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
                    _reexec(
                        [python_bin, str(entrypoint), *sys.argv[1:]],
                        {**os.environ, "MEMSEARCH_MAINTENANCE_UV_BOOTSTRAP": "1"},
                    )

    uv = shutil.which("uv")
    if not uv:
        return

    env = {**os.environ, "MEMSEARCH_MAINTENANCE_UV_BOOTSTRAP": "1"}
    _reexec(
        [
            uv,
            "run",
            "--with",
            "memsearch[onnx]",
            "python",
            str(entrypoint),
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
        cmd = [
            "claude",
            "-p",
            *claude_safe_mode_args(),
            "--strict-mcp-config",
            "--no-session-persistence",
            "--no-chrome",
        ]
        # Skill distillation needs to read original transcripts for exact commands.
        # Open a narrow hole — Bash limited to the two read-only memsearch drill
        # commands — only for that task; other maintenance keeps all tools off.
        if getattr(ctx, "task", "") == "memory_to_skill":
            cmd += ["--tools", "Bash", "--allowed-tools", "Bash(memsearch transcript:*) Bash(memsearch expand:*)"]
        else:
            cmd += ["--tools", ""]
        if model:
            cmd += ["--model", model]
        cmd += [
            "--system-prompt",
            "You are a maintenance task runner. Output only the requested JSON object.",
            prompt,
        ]
        env["CLAUDECODE"] = ""
        env["MEMSEARCH_DISABLE"] = "1"
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
        raise RuntimeError("OpenCode native maintenance requires the running V2 plugin's generation callback.")

    if ctx.platform == "dsh":
        # One-shot DSH headless agent; the model is the user's DSH default
        # (agent-default-model in ~/.dsh/settings.yaml). The headless runner
        # prints the final assistant text to stdout; for maintenance the agent
        # is instructed to output only a JSON object, which we then extract.
        # DSH_CLI may be a full command line (e.g. `node /path/to/bin.js`).
        cli = os.environ.get("DSH_CLI", "dsh").strip()
        cmd = [*shlex.split(cli), "--profile", "headless"]
        if model:
            cmd += ["--patch", f"agent-default-model={{model:{model}}}"]
        cmd.append(prompt)
        env["MEMSEARCH_DSH_SUMMARIZE"] = "1"  # keep the plugin inert inside the sub-agent
        env["MEMSEARCH_DISABLE"] = "1"
        out = run_command(cmd, env=env, cwd=ctx.project_dir, timeout=180)
        return extract_task_json_output(out)

    raise RuntimeError(f"Unsupported native maintenance platform {ctx.platform!r}")


def run_maintenance(platform, project_dir, memsearch_dir, cfg, *, native_runner=None, force=False):
    """Run shared maintenance with an optional host-owned stateless generator."""
    from memsearch.maintenance import run_due_tasks, run_task_llm

    apply_plugin_prompt_defaults(cfg)

    def llm_runner(ctx, prompt: str) -> str:
        provider_name = (ctx.task_config.provider or "native").strip()
        if provider_name in {"", "native"}:
            return (native_runner or run_native_provider)(ctx, prompt)
        return run_task_llm(ctx, prompt, cfg)

    results = run_due_tasks(
        platform=platform,
        project_dir=project_dir,
        memsearch_dir=memsearch_dir,
        cfg=cfg,
        force=force,
        llm_runner=llm_runner,
    )

    # Distill recurring workflows into candidate skills (procedural memory).
    # Same session-end trigger, due-state, and llm_runner as the tasks above;
    # this only ever touches the candidate store, never an agent's skills dir.
    from memsearch.skills import distill as distill_skills

    skill_result = distill_skills(
        platform=platform,
        project_dir=project_dir,
        memsearch_dir=memsearch_dir,
        cfg=cfg,
        force=force,
        llm_runner=llm_runner,
    )
    return results, skill_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run plugin-local MemSearch maintenance tasks.")
    parser.add_argument("--platform", required=True, choices=["claude-code", "codex", "opencode", "openclaw", "dsh"])
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--memsearch-dir", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()

    old_cwd = Path.cwd()
    try:
        ensure_memsearch_importable()
        from memsearch.config import resolve_config

        project_dir = Path(args.project_dir or old_cwd).expanduser().resolve()
        os.chdir(project_dir)
        cfg = resolve_config()

        results, skill_result = run_maintenance(
            args.platform,
            project_dir,
            args.memsearch_dir,
            cfg,
            force=args.force,
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
