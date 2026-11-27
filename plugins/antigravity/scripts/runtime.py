#!/usr/bin/env python3
"""Antigravity hooks, durable capture worker, and scoped CLI adapter.

The hook path uses only the standard library. It snapshots the completed turn
before detaching; model calls and Milvus clients exist only in the worker.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
HINT = "[memsearch] Recall available if needed: use memory-recall for project history (search → expand → transcript)."


def shell_command(arguments: list[str]) -> str:
    return subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)


class LocalDatabaseBusy(RuntimeError):
    safe_reason = "Local memory database is busy; retry after the active index or recall finishes."


@contextlib.contextmanager
def local_db_access(uri: str, *, timeout: float = 30):
    """Serialize Antigravity clients sharing one Lite file, across workspaces."""
    if uri.startswith(("http", "tcp", "unix:")):
        yield
        return
    from filelock import FileLock, Timeout

    database = Path(uri).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(database.with_name(database.name + ".antigravity.lock")))
    try:
        lock.acquire(timeout=timeout)
    except Timeout:
        raise LocalDatabaseBusy(LocalDatabaseBusy.safe_reason) from None
    try:
        yield
    finally:
        lock.release()


def roots(payload: dict) -> tuple[Path, Path]:
    workspaces = payload.get("workspacePaths")
    if not isinstance(workspaces, list) or not workspaces:
        raise ValueError("Hook input requires workspacePaths")
    candidates = [
        Path(p).expanduser().resolve()
        for p in workspaces
        if isinstance(p, str) and Path(p).expanduser().is_absolute() and Path(p).expanduser().is_dir()
    ]
    if not candidates:
        raise ValueError("workspacePaths must contain an existing absolute workspace")
    # The host's payload cwd is the conversation directory, distinct from the
    # hook process cwd (the plugin root). Keep collection scope at a mounted
    # workspace root even when the conversation cwd is a nested directory.
    project = candidates[0]
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and Path(cwd).is_absolute() and Path(cwd).is_dir():
        matching = [p for p in candidates if Path(cwd).resolve().is_relative_to(p)]
        if matching:
            project = max(matching, key=lambda p: len(p.parts))
    memory = Path(os.environ.get("MEMSEARCH_DIR") or project / ".memsearch").expanduser()
    if not memory.is_absolute():
        memory = project / memory
    return project, memory.resolve()


def collection(project: Path, memory: Path) -> str:
    scope = memory if os.environ.get("MEMSEARCH_DIR") else project
    name = re.sub(r"[^a-z0-9]+", "_", scope.name.lower()).strip("_")[:40]
    return f"ms_{name}_{hashlib.sha256(scope.as_posix().encode()).hexdigest()[:8]}"


def write_json(path: Path, value: dict, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            with contextlib.suppress(FileExistsError):
                os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_entries(path: Path) -> list[dict]:
    """Read backward only as far as the latest explicit user turn.

    Long-running sessions must not make a synchronous Stop hook parse the
    entire history. Fix the file extent at open time, before the next turn.
    """
    entries = []

    def reversed_lines():
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            remainder = b""
            while position:
                size = min(position, 65536)
                position -= size
                stream.seek(position)
                lines = (stream.read(size) + remainder).split(b"\n")
                remainder = lines[0]
                yield from reversed(lines[1:])
            yield remainder

    for line in reversed_lines():
        with contextlib.suppress(ValueError, UnicodeError):
            item = json.loads(line)
            if isinstance(item, dict):
                entries.append(item)
                if item.get("type") == "USER_INPUT" and item.get("source") in (None, "USER_EXPLICIT"):
                    break
    return list(reversed(entries))


def snapshot(payload: dict, project: Path, memory: Path) -> Path | None:
    reason = str(payload.get("terminationReason") or "").upper()
    if (
        payload.get("fullyIdle") is not True
        or payload.get("error")
        or payload.get("continuationActive")
        or reason not in ("", "NO_TOOL_CALL", "MODEL_STOP")
    ):
        return None
    transcript = Path(payload.get("transcriptPath") or "").expanduser()
    if not transcript.is_absolute() or not transcript.is_file():
        return None
    entries = read_entries(transcript)
    companion = transcript.with_name("transcript_full.jsonl")
    if transcript.name == "transcript.jsonl" and companion.is_file():
        full = {e.get("step_index"): e for e in read_entries(companion)}
        entries = [full.get(e.get("step_index"), e) for e in entries]
    start = next(
        (
            i
            for i in range(len(entries) - 1, -1, -1)
            if entries[i].get("type") == "USER_INPUT" and entries[i].get("source") in (None, "USER_EXPLICIT")
        ),
        None,
    )
    if start is None or not any(e.get("type") == "PLANNER_RESPONSE" for e in entries[start + 1 :]):
        return None
    turn = str(entries[start].get("step_index", ""))
    session = str(payload.get("conversationId") or "")
    if not turn or not session:
        return None
    identity = hashlib.sha256(f"{session}\0{turn}".encode()).hexdigest()
    job = memory / ".antigravity" / "jobs" / f"{identity}.json"
    now = datetime.now(timezone.utc)
    # Only spoken rows are needed for a retry. Exact tool I/O stays in the
    # original public transcript for L3; thinking and metadata are never queued.
    spoken = []
    for entry in entries[start:]:
        if entry.get("type") not in ("USER_INPUT", "PLANNER_RESPONSE") or not entry.get("content"):
            continue
        row = {key: entry[key] for key in ("step_index", "source", "type", "content", "created_at") if key in entry}
        if row["type"] == "USER_INPUT":
            match = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", str(row["content"]), re.DOTALL)
            if match:
                row["content"] = match.group(1)
        spoken.append(row)
    write_json(
        job,
        {
            "id": identity,
            "project": str(project),
            "memory": str(memory),
            "collection": collection(project, memory),
            "session": session,
            "turn": turn,
            "transcript": str(transcript),
            "entries": spoken,
            "created_at": entries[start].get("created_at") or now.isoformat(),
            "captured_at": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "stage": "captured",
        },
        exclusive=True,
    )
    return job


def has_pending(memory: Path) -> bool:
    for path in (memory / ".antigravity/jobs").glob("*.json"):
        with contextlib.suppress(OSError, ValueError):
            if json.loads(path.read_text(encoding="utf-8")).get("stage") not in ("done", "disabled"):
                return True
    return False


def detach(project: Path, memory: Path) -> None:
    subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "worker",
            "--project-dir",
            str(project),
            "--memsearch-dir",
            str(memory),
        ],
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
        env={**os.environ, "MEMSEARCH_AGY_WORKER": "1"},
    )


def hook(event: str, payload: dict) -> dict:
    if any(os.environ.get(key) == "1" for key in ("MEMSEARCH_DISABLE", "MEMSEARCH_AGY_HELPER", "MEMSEARCH_AGY_WORKER")):
        return {}
    project, memory = roots(payload)
    if event == "stop":
        if snapshot(payload, project, memory):
            detach(project, memory)
        return {}
    if event == "session-start" and has_pending(memory):
        detach(project, memory)
    # Inject once per session: PreInvocation can fire repeatedly within a turn,
    # and every injected step remains in the host's history.
    session = str(payload.get("conversationId") or "")
    if not session:
        return {}
    marker = memory / ".antigravity" / "hints" / hashlib.sha256(session.encode()).hexdigest()
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        marker.touch(exist_ok=False)
    except FileExistsError:
        return {}
    context = [
        HINT,
        f"Workspace: {project}\nMemory: {memory}",
        "Scoped CLI: "
        + shell_command(["python3", str(PLUGIN / "scripts/runtime.py"), "cli", "--project-dir", str(project), "--"])
        + " <command>",
    ]
    for name in ("PROJECT.md", "USER.md"):
        path = memory / name
        if path.is_file():
            with path.open(encoding="utf-8", errors="replace") as stream:
                context.append(f"MemSearch {name}:\n{stream.read(2000)}")
    return {"injectSteps": [{"systemMessage": {"systemMessage": "\n\n".join(context)}}]}


def config(project: Path, memory: Path, default_collection: str):
    from memsearch.config import resolve_config

    # The worker's cwd has been set to the hook workspace before resolution.
    cfg = resolve_config(
        default_overrides={"embedding": {"provider": "onnx"}, "milvus": {"collection": default_collection}}
    )
    # Keep explicit output conventions, but relocate default artifacts together
    # with an explicit MEMSEARCH_DIR. Other hosts retain their current behavior.
    platform = cfg.plugins.antigravity
    for task, filename in ((platform.project_review, "PROJECT.md"), (platform.user_profile, "USER.md")):
        if task.output_file == f".memsearch/{filename}":
            task.output_file = str(memory / filename)
    for task in ("summarize", "project_review", "user_profile", "memory_to_skill"):
        if not getattr(cfg.prompts, task):
            setattr(cfg.prompts, task, str(PLUGIN / "prompts" / f"{task}.txt"))
    return cfg


def summarize(job: dict, cfg) -> str:
    import asyncio

    from memsearch.compact import summarize_text
    from memsearch.transcript import _parse_antigravity, last_exchange

    exchange = last_exchange(_parse_antigravity(job["entries"]))
    if not exchange.get("text"):
        raise ValueError("No completed spoken exchange in snapshot")
    template = Path(cfg.prompts.summarize).expanduser().read_text(encoding="utf-8")
    prompt = template.replace("{{AGENT_NAME}}", "Antigravity") + "\n\nTranscript:\n" + exchange["text"]
    task = cfg.plugins.antigravity.summarize
    if task.provider in ("", "native"):
        from agy_native import generate

        result = generate(prompt, model=task.model)
    else:
        provider = cfg.llm.providers.get(task.provider)
        if provider is None:
            raise ValueError("Unknown named summary provider")
        result = asyncio.run(
            summarize_text(
                prompt,
                llm_provider=provider.type or task.provider,
                model=task.model or provider.model or None,
                base_url=provider.base_url or None,
                api_key=provider.api_key or None,
            )
        )
    if not isinstance(result, str) or not result.strip():
        raise ValueError("Summary provider returned no text")
    return result.strip()


def append_summary(job: dict, memory: Path) -> None:
    from filelock import FileLock

    journal = memory / "memory" / f"{job['date']}.md"
    journal.parent.mkdir(parents=True, exist_ok=True)
    marker = f"<!-- memsearch-antigravity:{job['id']} -->"
    with FileLock(str(memory / ".antigravity" / "append.lock"), timeout=60):
        existing = journal.read_text(encoding="utf-8") if journal.exists() else ""
        if marker in existing:
            return
        # Percent encoding keeps the existing core anchor format unambiguous
        # for transcript paths containing whitespace; L3 decodes local paths.
        from urllib.parse import quote

        path = quote(job["transcript"], safe="/\\:~")
        anchor = f"<!-- session:{job['session']} turn:{job['turn']} transcript:{path} -->"
        if not existing:
            existing = f"# {job['date']}\n\n"
        session_header = f"## Session {job['session']}"
        section = "" if session_header in existing else session_header + "\n\n"
        section += f"### {job['time']}\n{anchor}\n{marker}\n{job['summary']}\n\n"
        fd, name = tempfile.mkstemp(prefix=".journal-", dir=journal.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(existing + section)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, journal)
        finally:
            Path(name).unlink(missing_ok=True)


def run_index(memory: Path, cfg) -> None:
    try:
        with local_db_access(cfg.milvus.uri):
            _run_index(memory, cfg)
    except LocalDatabaseBusy as exc:
        from memsearch.index_state import record_index_error

        record_index_error(
            memory / ".index-state.json",
            exc,
            operation="index",
            paths=[str(memory / "memory")],
            collection=cfg.milvus.collection,
            milvus_uri=cfg.milvus.uri,
        )
        raise


def _run_index(memory: Path, cfg) -> None:
    import asyncio

    from memsearch import MemSearch
    from memsearch.cli import _cfg_to_memsearch_kwargs
    from memsearch.index_state import record_index_error, record_index_report

    state = memory / ".index-state.json"
    paths = [str(memory / "memory")]
    ms = None
    try:
        ms = MemSearch(paths, **_cfg_to_memsearch_kwargs(cfg))
        report = asyncio.run(ms.index_with_report())
    except Exception as exc:
        record_index_error(
            state, exc, operation="index", paths=paths, collection=cfg.milvus.collection, milvus_uri=cfg.milvus.uri
        )
        raise
    finally:
        if ms is not None:
            ms.close()
    record_index_report(
        state, report, operation="index", paths=paths, collection=cfg.milvus.collection, milvus_uri=cfg.milvus.uri
    )
    if report.failed_files:
        raise RuntimeError("Index has failed files")


def maintenance(project: Path, memory: Path, cfg, *, force: bool = False):
    path = PLUGIN / "scripts/maintenance-runner.py"
    spec = importlib.util.spec_from_file_location("antigravity_maintenance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results, skills = module.run_maintenance("antigravity", project, memory, cfg, force=force)
    write_json(
        memory / ".antigravity/maintenance-result.json",
        {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "tasks": [r.__dict__ for r in results],
            "memory_to_skill": skills.__dict__,
        },
    )
    return results, skills


def worker(project: Path, memory: Path) -> None:
    from filelock import FileLock

    queue = memory / ".antigravity" / "jobs"
    queue.mkdir(parents=True, exist_ok=True)
    # Every detached worker eventually drains the queue. A blocking kernel lock
    # avoids the lost-wakeup race between a finishing worker and a new Stop.
    with FileLock(str(queue.parent / "worker.lock")):
        worker_state = queue.parent / "worker.json"
        write_json(
            worker_state,
            {"pid": os.getpid(), "status": "running", "started_at": datetime.now(timezone.utc).isoformat()},
        )
        cfg = config(project, memory, collection(project, memory))
        pending = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in queue.glob("*.json")]
        pending.sort(
            key=lambda item: (
                item[1].get("created_at", item[1]["date"] + "T" + item[1]["time"]),
                item[1]["session"],
                int(item[1]["turn"]),
            )
        )
        for path, job in pending:
            if job["stage"] in ("done", "disabled"):
                continue
            try:
                write_json(
                    worker_state, {"pid": os.getpid(), "status": "running", "job": job["id"], "stage": job["stage"]}
                )
                cfg = config(project, memory, job["collection"])
                if job["stage"] == "captured":
                    if not cfg.plugins.antigravity.summarize.enabled:
                        job["stage"] = "disabled"
                    else:
                        job["summary_attempts"] = job.get("summary_attempts", 0) + 1
                        write_json(path, job)
                        job["summary"] = summarize(job, cfg)
                        job["stage"] = "summarized"
                    job.pop("entries", None)
                    write_json(path, job)
                if job["stage"] == "summarized":
                    append_summary(job, memory)
                    job["stage"] = "written"
                    write_json(path, job)
                if job["stage"] == "written":
                    run_index(memory, cfg)
                    job["stage"] = "done"
                    job.pop("summary", None)
                    job.pop("last_error", None)
                    job.pop("last_error_reason", None)
                    write_json(path, job)
            except Exception as exc:
                # Detailed provider output can contain credentials or prompts.
                job["last_error"] = type(exc).__name__
                job["last_error_reason"] = getattr(exc, "safe_reason", None) or {
                    "captured": "Summary failed; check the configured provider/model and native login.",
                    "summarized": "Journal write failed; check the memory directory permissions.",
                    "written": "Index failed; Markdown is preserved. Check .index-state.json and backend availability.",
                }.get(job["stage"], "Background capture failed.")
                job["last_failed_at"] = datetime.now(timezone.utc).isoformat()
                write_json(path, job)
                if job["stage"] in ("captured", "summarized"):
                    # Preserve correction order when an older turn cannot yet
                    # be summarized or journaled. Index outages do not block
                    # later Markdown capture because that earlier entry exists.
                    break
        # Index clients have been closed before any maintenance model call.
        try:
            maintenance(project, memory, cfg)
        except Exception as exc:
            write_json(queue.parent / "maintenance-error.json", {"error": type(exc).__name__})
        write_json(
            worker_state, {"pid": os.getpid(), "status": "idle", "finished_at": datetime.now(timezone.utc).isoformat()}
        )


def scoped_cli(arguments: list[str], cfg) -> None:
    from memsearch import cli as cli_module
    from memsearch.config import deep_merge

    original = cli_module.resolve_config
    access = contextlib.ExitStack()
    locked = set()

    def resolved(overrides=None, *, default_overrides=None):
        defaults = {"embedding": {"provider": "onnx"}, "milvus": {"collection": cfg.milvus.collection}}
        resolved_cfg = original(overrides, default_overrides=deep_merge(defaults, default_overrides or {}))
        # Acquire after explicit CLI URI overrides have been resolved. Keep
        # the lock through client.close(), but never through model generation.
        if arguments and arguments[0] in {"index", "search", "expand", "stats", "watch", "drop"}:
            uri = resolved_cfg.milvus.uri
            if uri not in locked:
                access.enter_context(local_db_access(uri))
                locked.add(uri)
        return resolved_cfg

    cli_module.resolve_config = resolved
    try:
        cli_module.cli.main(args=arguments, prog_name="memsearch")
    finally:
        cli_module.resolve_config = original
        access.close()


def main() -> int:
    from bootstrap import bootstrap, require_core

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=("session-start", "pre-invocation", "stop", "worker", "maintenance", "cli"))
    parser.add_argument("--project-dir")
    parser.add_argument("--memsearch-dir")
    parser.add_argument("--force", action="store_true")
    args, remainder = parser.parse_known_args()
    if args.event in ("session-start", "pre-invocation", "stop"):
        try:
            result = hook(args.event, json.load(sys.stdin))
        except (OSError, ValueError, TypeError):
            result = {}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        return 0
    bootstrap(Path(__file__).resolve())
    require_core()
    if args.memsearch_dir and args.event != "worker":
        os.environ["MEMSEARCH_DIR"] = args.memsearch_dir
    project, memory = roots({"workspacePaths": [str(Path(args.project_dir or Path.cwd()).resolve())]})
    if args.memsearch_dir:
        memory = Path(args.memsearch_dir).expanduser()
        memory = (memory if memory.is_absolute() else project / memory).resolve()
    os.chdir(project)
    if args.event == "worker":
        worker(project, memory)
    elif args.event == "maintenance":
        from filelock import FileLock

        cfg = config(project, memory, collection(project, memory))
        (memory / ".antigravity").mkdir(parents=True, exist_ok=True)
        with FileLock(str(memory / ".antigravity/worker.lock")):
            results, skills = maintenance(project, memory, cfg, force=args.force)
        sys.stdout.write(
            json.dumps(
                [r.__dict__ for r in results] + [{"task": "memory_to_skill", **skills.__dict__}], ensure_ascii=False
            )
            + "\n"
        )
    else:
        scoped_cli(
            remainder[1:] if remainder[:1] == ["--"] else remainder,
            config(project, memory, collection(project, memory)),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
