"""Background maintenance tasks for plugin-managed memories."""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import stat as stat_module
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from ._maintenance_lock import file_lock as _file_lock
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

# Windows gate for the find/grep subset and path-separator-aware splitting.
# A module constant rather than an inline os.name check: pathlib dispatches on
# os.name at every Path() call, so tests that patch os.name would break Path
# itself; patching this constant keeps the platform seam in one place.
_ON_WINDOWS = os.name == "nt"


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
            try:
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
            except Exception as exc:
                _record_failure_state(
                    state,
                    state_path,
                    state_key,
                    input_digest=digest,
                    output_file=output_file,
                    error=exc,
                )
                raise

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
    journal_budget = max(
        0,
        MAX_PROMPT_CHARS - len(template) - len(existing) - 512,
    )
    journals = _read_recent_journals(
        ctx.input_dir,
        budget=journal_budget,
    )
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


def _read_recent_journals(
    input_dir: Path,
    max_files: int = 12,
    budget: int | None = None,
) -> str:
    if not input_dir.is_dir():
        return ""
    chunks: list[str] = []
    files = sorted(
        (p for p in input_dir.rglob("*.md") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )[-max_files:]
    for path in files:
        with contextlib.suppress(OSError):
            chunks.append(f"\n<!-- source:{path} -->\n{read_utf8_text_replace(path)}")
    text = "\n".join(chunks)
    if budget is None or len(text) <= budget:
        return text
    if budget <= 0:
        return ""
    marker = "[older journal entries truncated]\n"
    if budget <= len(marker):
        return text[-budget:]
    return marker + text[-(budget - len(marker)) :]


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
    # Preserve the normal closing request; retry only a proven incompatibility.
    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=messages,
            tools=tools,
            tool_choice="none",
        )
    except openai.APIStatusError as exc:
        if not _unsupported_tool_choice(exc):
            raise
        closing_failure = f"tool_choice=none was rejected (HTTP {exc.status_code})"
    else:
        if not resp.choices[0].message.tool_calls:
            return _openai_final_text(resp.choices[0])
        closing_failure = "the endpoint returned tool calls despite tool_choice=none"

    # Keep the completed drill history, without adding unanswered tool calls
    # from the rejected closing response. Never execute more tools here.
    resp = client.chat.completions.create(model=chosen_model, messages=messages)
    if resp.choices[0].message.tool_calls:
        raise RuntimeError(f"Memory maintenance final request returned tool calls without tools ({closing_failure})")
    return _openai_final_text(resp.choices[0])


def _unsupported_tool_choice(exc: Any) -> bool:
    """Recognize an explicit parameter/value rejection, not an arbitrary API error."""
    if exc.status_code not in (400, 422):
        return False
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error", body)
    if not isinstance(error, dict):
        error = {}
    param = error.get("param") or getattr(exc, "param", None)
    if param and param != "tool_choice":
        return False
    code = error.get("code") or getattr(exc, "code", None)
    if param == "tool_choice" and code in {
        "unsupported_parameter",
        "unsupported_value",
        "unsupported_parameter_value",
        "unknown_parameter",
    }:
        return True
    message = str(error.get("message") or exc.message).lower().replace("_", " ")
    return (param == "tool_choice" or "tool choice" in message) and any(
        marker in message
        for marker in (
            "not supported",
            "unsupported",
            "not support",
            "only auto",
            "must be auto",
            "only 'auto'",
            'only "auto"',
        )
    )


def _openai_final_text(choice: Any) -> str:
    content = choice.message.content or ""
    if not content.strip():
        raise RuntimeError(f"Memory maintenance final request returned no text; finish_reason={choice.finish_reason!r}")
    return content


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
        argv = _split_command(command)
    except ValueError as e:
        return f"Error: {e}"
    if not argv:
        return "Error: empty command"

    allowed_roots = [ctx.project_dir, ctx.input_dir, ctx.memsearch_dir]
    executable = argv[0]
    if executable == "memsearch":
        if len(argv) < 2 or argv[1] not in {"expand", "transcript"}:
            return "Error: only memsearch expand/transcript are allowed"
        # `transcript` is a bounded, read-only formatter — it only reads a session
        # transcript and prints its turns. The original transcript lives outside the
        # memory roots (e.g. ~/.claude/projects), so the path check is skipped here;
        # the command itself is the boundary.
        if argv[1] == "transcript":
            return _run_restricted(argv, ctx.project_dir)
        checked = _validate_paths_in_args(argv[2:], allowed_roots, cwd=ctx.project_dir, allow_hash=True)
        if checked:
            return checked
        return _run_restricted(argv, ctx.project_dir)
    if executable in {"find", "grep"}:
        if _ON_WINDOWS:
            return _run_windows_memory_search(argv, ctx.project_dir, allowed_roots)
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


def _split_command(command: str) -> list[str]:
    """Split quoted arguments while preserving Windows path separators."""
    if not _ON_WINDOWS:
        return shlex.split(command)
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    return list(lexer)


def _entry_is_reparse(st: os.stat_result) -> bool:
    """True for symlink/reparse entries, which the search never traverses.

    Windows reports reparse points through ``st_file_attributes``; POSIX has
    no such field (hence ``getattr``), so symlinks are detected via the mode.
    """
    return bool(getattr(st, "st_file_attributes", 0) & 0x400) or stat_module.S_ISLNK(st.st_mode)


def _run_windows_memory_search(argv: list[str], cwd: Path, allowed_roots: list[Path]) -> str:
    """Small read-only find/grep subset, with no executable or shell dispatch.

    find PATH [-maxdepth N] -type f [-name GLOB]; grep [-rlnc] PATTERN
    PATH... . PATTERN is literal text (regular expressions are rejected).
    Links/reparse points are never traversed. Resource limits fail explicitly.
    """
    try:
        roots = [root.resolve(strict=True) for root in allowed_roots if root.exists()]

        def checked_path(raw: str) -> Path:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = cwd / path
            # A colon anywhere except a drive designator is an NTFS alternate
            # data stream, which must not bypass the ordinary file boundary.
            if ":" in str(path)[len(path.drive):]:
                raise ValueError("alternate data streams are not supported")
            # Reject lexical escapes (including UNC/device operands) before
            # resolve/stat can touch a location outside the configured roots.
            lexical = Path(os.path.abspath(path))
            if not any(_is_relative_to(lexical, root) for root in roots):
                raise ValueError(f"path {raw!r} is outside allowed memory roots")
            resolved = path.resolve(strict=True)
            if not any(_is_relative_to(resolved, root) for root in roots):
                raise ValueError(f"path {raw!r} is outside allowed memory roots")
            for part in (path, *path.parents):
                if _entry_is_reparse(part.lstat()):
                    raise ValueError(f"links/reparse points are not supported: {raw!r}")
            return path

        mode = argv[0]
        depth_limit = None
        name = None
        flags: set[str] = set()
        if mode == "find":
            if len(argv) < 2 or argv[1].startswith("-"):
                raise ValueError("find requires PATH [-maxdepth N] -type f [-name GLOB]")
            paths = [checked_path(argv[1])]
            options: dict[str, str] = {}
            index = 2
            while index < len(argv):
                option = argv[index]
                if option not in {"-maxdepth", "-type", "-name"} or option in options or index + 1 >= len(argv):
                    raise ValueError(f"unsupported find option: {option!r}")
                options[option] = argv[index + 1]
                index += 2
            if options.get("-type") != "f":
                raise ValueError("find supports only -type f")
            if "-maxdepth" in options:
                if not options["-maxdepth"].isascii() or not options["-maxdepth"].isdecimal():
                    raise ValueError("-maxdepth requires a nonnegative integer")
                depth_limit = int(options["-maxdepth"])
            name = options.get("-name")
            if name is not None and ("/" in name or "\\" in name):
                raise ValueError("-name must be a basename glob")
            recursive = True
        else:
            index = 1
            while index < len(argv) and argv[index].startswith("-"):
                option = argv[index]
                if option == "--":
                    index += 1
                    break
                if len(option) < 2 or not set(option[1:]) <= set("rlnc"):
                    raise ValueError(f"unsupported grep option: {option!r}")
                flags.update(option[1:])
                index += 1
            if len(argv) - index < 2:
                raise ValueError("grep requires PATTERN PATH...")
            pattern = argv[index]
            if any(char in pattern for char in "\\.^$*+?[]{}()") or "\n" in pattern or "\r" in pattern:
                raise ValueError("grep supports literal single-line PATTERN only; regular expressions are not supported")
            operands = argv[index + 1:]
            if any(raw.startswith("-") for raw in operands):
                raise ValueError("grep options must precede PATTERN; use ./ for filenames beginning with '-'")
            paths = [checked_path(raw) for raw in operands]
            recursive = "r" in flags
            if not recursive and any(path.is_dir() for path in paths):
                raise ValueError("grep directory operands require -r")

        output: list[str] = []
        output_size = 0
        visited = 0
        scanned_bytes = 0

        def emit(text: str) -> bool:
            nonlocal output_size
            remaining = MAX_COMMAND_OUTPUT - output_size
            if remaining <= 0:
                return False
            piece = ("\n" if output else "") + text
            output.append(piece[:remaining])
            output_size += len(piece[:remaining])
            return len(piece) < remaining

        def files(path: Path, depth: int = 0):
            nonlocal visited
            visited += 1
            if visited > 10_000:
                raise ValueError("search entry limit exceeded (10000)")
            # Check every entry before opening or descending, including junctions.
            if _entry_is_reparse(path.lstat()):
                return
            checked_path(str(path))
            if path.is_file():
                yield path
            elif path.is_dir() and recursive and (depth_limit is None or depth < depth_limit):
                for child in path.iterdir():
                    yield from files(child, depth + 1)

        multiple = len(paths) > 1 or recursive
        for operand in paths:
            for path in files(operand):
                if mode == "find":
                    if name is None or fnmatch.fnmatchcase(path.name, name):
                        if not emit(str(path)):
                            return "".join(output)
                    continue
                # Bound bytes before decoding. Binary files are explicitly skipped.
                with path.open("rb") as stream:
                    data = stream.read(2_000_001)
                scanned_bytes += len(data)
                if len(data) > 2_000_000 or scanned_bytes > 20_000_000:
                    raise ValueError("grep byte limit exceeded (2MB/file, 20MB/search)")
                if b"\0" in data:
                    continue
                count = 0
                for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                    if pattern not in line:
                        continue
                    count += 1
                    if "l" in flags:
                        if not emit(str(path)):
                            return "".join(output)
                        break
                    if "c" not in flags:
                        prefix = f"{path}:" if multiple else ""
                        if "n" in flags:
                            prefix += f"{number}:"
                        if not emit(prefix + line):
                            return "".join(output)
                if "c" in flags and "l" not in flags:
                    if not emit((f"{path}:" if multiple else "") + str(count)):
                        return "".join(output)
        return "".join(output)
    except (OSError, ValueError, RuntimeError) as exc:
        return f"Error: {exc}"[:MAX_COMMAND_OUTPUT]


def _validate_paths_in_args(args: list[str], allowed_roots: list[Path], *, cwd: Path, allow_hash: bool) -> str:
    for arg in args:
        if arg.startswith("-") or arg in {"*.md", "'*.md'", '"*.md"'}:
            continue
        if allow_hash and re.fullmatch(r"[a-fA-F0-9]{8,64}", arg):
            continue
        windows_drive = os.name == "nt" and re.match(r"^[a-zA-Z]:", arg)
        if "/" not in arg and "\\" not in arg and not arg.startswith(".") and not windows_drive:
            continue
        path = Path(arg).expanduser()
        if not path.is_absolute():
            path = cwd / path
        try:
            resolved = path.resolve()
        except (OSError, ValueError) as exc:
            return f"Error: cannot resolve path {arg!r}: {exc}"
        if not any(_is_relative_to(resolved, root) for root in allowed_roots):
            return f"Error: path {arg!r} is outside allowed memory roots"
    return ""


def _is_relative_to(path: Path, root: Path) -> bool:
    with contextlib.suppress(ValueError):
        path.relative_to(root)
        return True
    return False


def _run_restricted(argv: list[str], cwd: Path) -> str:
    # Resolve like a shell so Windows .cmd/.bat shims are found; unresolvable
    # names pass through and fail the same way as before.
    argv = [shutil.which(argv[0]) or argv[0], *argv[1:]]
    # cmd.exe can expand these characters after the path check. Native
    # executables and POSIX commands receive their arguments literally.
    if (
        os.name == "nt"
        and Path(argv[0]).suffix.lower() in {".cmd", ".bat"}
        and any(re.search(r"[%!^]", arg) for arg in argv)
    ):
        return "Error: %, ! and ^ are not supported in Windows batch commands"
    text_options = {}
    if Path(argv[0]).stem.lower() == "memsearch":
        text_options = {"encoding": "utf-8", "errors": "strict"}
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            **text_options,
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
        # strict=False: models often emit the markdown `content` with raw newlines
        # inside the JSON string, which strict parsing rejects as control characters.
        data = json.loads(text, strict=False)
    except json.JSONDecodeError as initial_error:
        decoder = json.JSONDecoder(strict=False)
        last_object: dict[str, Any] | None = None
        last_action_object: dict[str, Any] | None = None

        cursor = 0
        while True:
            brace = text.find("{", cursor)
            bracket = text.find("[", cursor)
            starts = [position for position in (brace, bracket) if position >= 0]
            if not starts:
                break
            start = min(starts)

            try:
                candidate, end = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                stack: list[str] = []
                in_string = False
                escaped = False
                balanced_end: int | None = None

                for index in range(start, len(text)):
                    char = text[index]

                    if in_string:
                        if escaped:
                            escaped = False
                        elif char == "\\":
                            escaped = True
                        elif char == '"':
                            in_string = False
                        continue

                    if char == '"':
                        in_string = True
                    elif char in "{[":
                        stack.append(char)
                    elif char in "}]":
                        expected = "{" if char == "}" else "["
                        if not stack or stack[-1] != expected:
                            break
                        stack.pop()
                        if not stack:
                            balanced_end = index + 1
                            break

                if balanced_end is None:
                    break

                cursor = balanced_end
                continue

            cursor = end

            if not isinstance(candidate, dict):
                continue

            last_object = candidate
            if "action" in candidate:
                last_action_object = candidate

        data = last_action_object or last_object
        if data is None:
            raise RuntimeError(f"Maintenance LLM did not return valid JSON: {initial_error}") from initial_error

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


def _format_error(error: BaseException, limit: int = 2000) -> str:
    message = f"{type(error).__name__}: {error}"
    if len(message) > limit:
        return message[: limit - len("... [truncated]")] + "... [truncated]"
    return message


def _record_failure_state(
    state: dict[str, Any],
    state_path: Path,
    state_key: str,
    *,
    input_digest: str,
    output_file: Path,
    error: BaseException,
) -> None:
    now = _now()
    previous = state.get(state_key, {})
    entry = dict(previous) if isinstance(previous, dict) else {}
    entry.update(
        {
            "last_checked_at": now,
            "last_failed_at": now,
            "failed_input_digest": input_digest,
            "last_action": "error",
            "last_error": _format_error(error),
            "output_file": str(output_file),
        }
    )
    state[state_key] = entry
    _save_state(state_path, state)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
