"""Background maintenance tasks for plugin-managed memories."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from .compact import summarize_text
from .config import (
    LLMProviderConfig,
    MemSearchConfig,
    PluginMaintenanceTaskConfig,
    config_to_dict,
    resolve_env_ref,
)
from .io import read_utf8_text_replace

TASKS = ("project_review", "user_profile")
MAX_PROMPT_CHARS = 80_000
MAX_COMMAND_OUTPUT = 12_000
MAX_TOOL_CALLS = 3


@dataclass
class MaintenanceResult:
    task: str
    action: str
    reason: str = ""
    output_file: str = ""
    skipped: bool = False


@dataclass
class TaskContext:
    platform: str
    task: str
    task_config: PluginMaintenanceTaskConfig
    project_dir: Path
    memsearch_dir: Path
    input_dir: Path
    output_file: Path
    input_digest: str


def run_due_tasks(
    *,
    platform: str,
    project_dir: str | Path | None = None,
    memsearch_dir: str | Path | None = None,
    cfg: MemSearchConfig | None = None,
    force: bool = False,
    llm_runner: Callable[[TaskContext, str], str] | None = None,
) -> list[MaintenanceResult]:
    """Run enabled maintenance tasks that are due."""
    if cfg is None:
        from .config import resolve_config

        cfg = resolve_config()

    project_root = Path(project_dir or os.getcwd()).expanduser().resolve()
    mem_root = Path(memsearch_dir or os.environ.get("MEMSEARCH_DIR", project_root / ".memsearch")).expanduser()
    if not mem_root.is_absolute():
        mem_root = project_root / mem_root
    mem_root = mem_root.resolve()
    mem_root.mkdir(parents=True, exist_ok=True)

    state_path = mem_root / ".maintenance-state.json"
    state = _load_state(state_path)

    results: list[MaintenanceResult] = []
    for task_name in TASKS:
        task_cfg = _get_task_config(cfg, platform, task_name)
        if task_cfg is None or not task_cfg.enabled:
            results.append(MaintenanceResult(task=task_name, action="disabled", skipped=True))
            continue

        input_dir = _resolve_task_path(task_cfg.input_dir or str(mem_root / "memory"), project_root, mem_root)
        output_file = _resolve_task_path(task_cfg.output_file, project_root, mem_root)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        digest = _input_digest(input_dir)
        state_key = f"{platform}.{task_name}"
        task_state = state.get(state_key, {})
        due, reason = _is_due(task_cfg, task_state, digest, force)
        if not due:
            results.append(MaintenanceResult(task=task_name, action="skip", reason=reason, skipped=True))
            continue

        lock_path = mem_root / f".maintenance-{platform}-{task_name}.lock"
        with _file_lock(lock_path) as locked:
            if not locked:
                results.append(MaintenanceResult(task=task_name, action="locked", skipped=True))
                continue

            ctx = TaskContext(
                platform=platform,
                task=task_name,
                task_config=task_cfg,
                project_dir=project_root,
                memsearch_dir=mem_root,
                input_dir=input_dir,
                output_file=output_file,
                input_digest=digest,
            )
            prompt = _build_prompt(ctx, cfg)
            raw = llm_runner(ctx, prompt) if llm_runner else run_task_llm(ctx, prompt, cfg)
            parsed = _parse_task_response(raw)
            now = _now()

            if parsed["action"] == "replace":
                content = str(parsed.get("content") or "").strip()
                if not content:
                    raise RuntimeError(f"{task_name} returned replace without content")
                output_file.write_text(content.rstrip() + "\n", encoding="utf-8")
                action = "replace"
            else:
                action = "none"

            state[state_key] = {
                "last_checked_at": now,
                "last_success_at": now,
                "last_input_digest": digest,
                "last_action": action,
                "output_file": str(output_file),
            }
            _save_state(state_path, state)
            results.append(
                MaintenanceResult(
                    task=task_name,
                    action=action,
                    reason=str(parsed.get("reason") or ""),
                    output_file=str(output_file),
                )
            )

    return results


def _get_task_config(cfg: MemSearchConfig, platform: str, task_name: str) -> PluginMaintenanceTaskConfig | None:
    plugins = config_to_dict(cfg).get("plugins", {})
    platform_cfg = plugins.get(platform)
    if not isinstance(platform_cfg, dict):
        return None
    task_data = platform_cfg.get(task_name)
    if not isinstance(task_data, dict):
        return None
    return PluginMaintenanceTaskConfig(
        **{k: v for k, v in task_data.items() if k in PluginMaintenanceTaskConfig.__dataclass_fields__}
    )


def _resolve_task_path(raw_path: str, project_dir: Path, memsearch_dir: Path) -> Path:
    path_text = raw_path or ""
    if path_text == ".memsearch/memory":
        return (memsearch_dir / "memory").resolve()
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve()


def _input_digest(input_dir: Path) -> str:
    h = hashlib.sha256()
    if not input_dir.is_dir():
        return "sha256:empty"
    for path in sorted(input_dir.rglob("*.md")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(input_dir))
        h.update(rel.encode())
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return f"sha256:{h.hexdigest()}"


def _is_due(task_cfg: PluginMaintenanceTaskConfig, state: dict[str, Any], digest: str, force: bool) -> tuple[bool, str]:
    if force:
        return True, "force"
    if state.get("last_input_digest") == digest:
        return False, "input unchanged"
    last_success = state.get("last_success_at")
    if not last_success:
        return True, "never run"
    try:
        last_dt = datetime.fromisoformat(str(last_success).replace("Z", "+00:00"))
    except ValueError:
        return True, "invalid state timestamp"
    age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
    if age_hours < max(0, task_cfg.min_interval_hours):
        return False, f"not due for {task_cfg.min_interval_hours}h"
    return True, "due"


def _build_prompt(ctx: TaskContext, cfg: MemSearchConfig) -> str:
    template = _load_prompt_template(ctx.task, cfg)
    replacements = {
        "{{AGENT_NAME}}": ctx.platform,
        "{{TASK_NAME}}": ctx.task,
        "{{PROJECT_DIR}}": str(ctx.project_dir),
        "{{INPUT_DIR}}": str(ctx.input_dir),
        "{{OUTPUT_FILE}}": str(ctx.output_file),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)

    existing = ctx.output_file.read_text(encoding="utf-8") if ctx.output_file.is_file() else ""
    journals = _read_recent_journals(ctx.input_dir)
    prompt = f"""{template}

## Existing output file

```markdown
{existing.strip()}
```

## Recent memory journal entries

```markdown
{journals.strip()}
```

## Changed input digest

{ctx.input_digest}
"""
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n\n[truncated]\n"
    return prompt


def _load_prompt_template(task: str, cfg: MemSearchConfig) -> str:
    configured = getattr(cfg.prompts, task, "")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8")
    with resources.files("memsearch.prompts").joinpath(f"{task}.txt").open("r", encoding="utf-8") as f:
        return f.read()


def _read_recent_journals(input_dir: Path, max_files: int = 12) -> str:
    if not input_dir.is_dir():
        return ""
    chunks: list[str] = []
    files = sorted((p for p in input_dir.rglob("*.md") if p.is_file()), key=lambda p: p.stat().st_mtime)[-max_files:]
    for path in files:
        with contextlib.suppress(OSError):
            chunks.append(f"\n<!-- source:{path} -->\n{read_utf8_text_replace(path)}")
    return "\n".join(chunks)


def run_task_llm(ctx: TaskContext, prompt: str, cfg: MemSearchConfig) -> str:
    """Run a memsearch-managed API provider for a maintenance task.

    Host-native providers are handled by plugin-local runners because the
    invocation details belong to each plugin host, not the Python core.
    """
    provider_name = (ctx.task_config.provider or "native").strip()
    if provider_name == "native":
        raise RuntimeError("Native maintenance providers must be handled by the plugin runner")

    provider_cfg = cfg.llm.providers.get(provider_name)
    if provider_cfg is None:
        raise RuntimeError(f"Unknown LLM provider {provider_name!r}")
    provider_type = provider_cfg.type or provider_name
    model = ctx.task_config.model or provider_cfg.model or None

    if provider_type in {"openai", "openai-compatible"}:
        return _run_openai_with_tools(ctx, prompt, provider_type, model, provider_cfg)
    if provider_type == "anthropic":
        return _run_anthropic_with_tools(ctx, prompt, model, provider_cfg)
    if provider_type == "gemini":
        return _run_gemini_with_tools(ctx, prompt, model, provider_cfg)

    return _run_async_summarize_text(prompt, provider_type, model, provider_cfg)


def _run_async_summarize_text(
    prompt: str, provider_type: str, model: str | None, provider_cfg: LLMProviderConfig
) -> str:
    import asyncio

    return asyncio.run(
        summarize_text(
            prompt,
            llm_provider=provider_type,
            model=model,
            base_url=provider_cfg.base_url or None,
            api_key=provider_cfg.api_key or None,
        )
    )


def _run_openai_with_tools(
    ctx: TaskContext, prompt: str, provider_type: str, model: str | None, provider_cfg: LLMProviderConfig
) -> str:
    import openai

    kwargs: dict[str, str] = {}
    base_url = resolve_env_ref(provider_cfg.base_url) if provider_cfg.base_url else os.environ.get("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    if provider_cfg.api_key:
        kwargs["api_key"] = resolve_env_ref(provider_cfg.api_key)
    client = openai.OpenAI(**kwargs)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tools = [_openai_memory_tool_schema()]
    chosen_model = model or "gpt-5-mini"
    tool_call_count = 0
    for _ in range(MAX_TOOL_CALLS):
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            return msg.content or ""
        messages.append(msg.model_dump(exclude_none=True))
        for call in tool_calls:
            if tool_call_count < MAX_TOOL_CALLS:
                args = json.loads(call.function.arguments or "{}")
                output = run_memory_command(str(args.get("command", "")), ctx)
                tool_call_count += 1
            else:
                output = "Error: memory tool call limit reached"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": output,
                }
            )
    resp = client.chat.completions.create(
        model=chosen_model,
        messages=messages,
        tools=tools,
        tool_choice="none",
    )
    return resp.choices[0].message.content or ""


def _openai_memory_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "run_memory_command",
            "description": "Run a restricted read-only memsearch memory drill-down command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "A read-only command such as memsearch expand, memsearch transcript, find, or grep under the memory input directory.",
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    }


def _run_anthropic_with_tools(ctx: TaskContext, prompt: str, model: str | None, provider_cfg: LLMProviderConfig) -> str:
    import anthropic

    api_key = resolve_env_ref(provider_cfg.api_key) if provider_cfg.api_key else None
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    chosen_model = model or "claude-sonnet-4-6"
    for _ in range(MAX_TOOL_CALLS):
        resp = client.messages.create(
            model=chosen_model,
            max_tokens=4096,
            tools=[_anthropic_memory_tool_schema()],
            messages=messages,
        )
        text_parts: list[str] = []
        tool_results: list[dict[str, Any]] = []
        assistant_content: list[Any] = []
        for block in resp.content:
            assistant_content.append(block)
            if getattr(block, "type", "") == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", "") == "tool_use":
                command = str((block.input or {}).get("command", ""))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": run_memory_command(command, ctx),
                    }
                )
        if not tool_results:
            return "\n".join(text_parts).strip()
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})
    resp = client.messages.create(
        model=chosen_model,
        max_tokens=4096,
        messages=messages,
    )
    return "\n".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()


def _anthropic_memory_tool_schema() -> dict[str, Any]:
    return {
        "name": "run_memory_command",
        "description": "Run a restricted read-only memsearch memory drill-down command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    }


def _run_gemini_with_tools(ctx: TaskContext, prompt: str, model: str | None, provider_cfg: LLMProviderConfig) -> str:
    from google import genai
    from google.genai import types

    api_key = resolve_env_ref(provider_cfg.api_key) if provider_cfg.api_key else None
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    chosen_model = model or "gemini-3-flash-preview"

    def run_memory_command_tool(command: str) -> str:
        """Run a restricted read-only memsearch memory drill-down command."""
        return run_memory_command(command, ctx)

    resp = client.models.generate_content(
        model=chosen_model,
        contents=prompt,
        config=types.GenerateContentConfig(tools=[run_memory_command_tool], temperature=0.2),
    )
    return resp.text or ""


def run_memory_command(command: str, ctx: TaskContext) -> str:
    """Run a restricted read-only memory command."""
    if not command.strip():
        return "Error: empty command"
    if re.search(r"[|;&<>`$(){}]", command):
        return "Error: shell metacharacters are not allowed"
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return f"Error: {e}"
    if not argv:
        return "Error: empty command"

    allowed_roots = [ctx.project_dir, ctx.input_dir, ctx.memsearch_dir]
    executable = argv[0]
    if executable == "memsearch":
        if len(argv) < 2 or argv[1] not in {"expand", "transcript"}:
            return "Error: only memsearch expand/transcript are allowed"
        checked = _validate_paths_in_args(argv[2:], allowed_roots, cwd=ctx.project_dir, allow_hash=True)
        if checked:
            return checked
        return _run_restricted(argv, ctx.project_dir)
    if executable in {"find", "grep"}:
        checked = _validate_paths_in_args(argv[1:], allowed_roots, cwd=ctx.project_dir, allow_hash=False)
        if checked:
            return checked
        return _run_restricted(argv, ctx.project_dir)
    if executable == "python3" and len(argv) >= 2 and argv[1].endswith("parse-transcript.py"):
        checked = _validate_paths_in_args(argv[1:], allowed_roots, cwd=ctx.project_dir, allow_hash=False)
        if checked:
            return checked
        return _run_restricted(argv, ctx.project_dir)
    return f"Error: command {executable!r} is not allowed"


def _validate_paths_in_args(args: list[str], allowed_roots: list[Path], *, cwd: Path, allow_hash: bool) -> str:
    for arg in args:
        if arg.startswith("-") or arg in {"*.md", "'*.md'", '"*.md"'}:
            continue
        if allow_hash and re.fullmatch(r"[a-fA-F0-9]{8,64}", arg):
            continue
        if "/" not in arg and not arg.startswith("."):
            continue
        path = Path(arg).expanduser()
        if not path.is_absolute():
            path = cwd / path
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not any(_is_relative_to(resolved, root) for root in allowed_roots):
            return f"Error: path {arg!r} is outside allowed memory roots"
    return ""


def _is_relative_to(path: Path, root: Path) -> bool:
    with contextlib.suppress(ValueError):
        path.relative_to(root)
        return True
    return False


def _run_restricted(argv: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            env={**os.environ, "MEMSEARCH_NO_WATCH": "1"},
            timeout=15,
            check=False,
        )
    except Exception as e:
        return f"Error: {e}"
    output = (result.stdout or result.stderr or "").strip()
    return output[:MAX_COMMAND_OUTPUT]


def _parse_task_response(raw: str) -> dict[str, str]:
    text = raw.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Maintenance LLM did not return valid JSON: {e}") from e
    action = data.get("action")
    if action not in {"none", "replace"}:
        raise RuntimeError("Maintenance LLM action must be 'none' or 'replace'")
    return data


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with contextlib.suppress(json.JSONDecodeError, OSError):
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@contextlib.contextmanager
def _file_lock(path: Path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        yield True
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            path.unlink()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
