#!/usr/bin/env python3
"""Opt-in native Antigravity TUI evidence harness.

Use an authenticated native agy installation and cached ONNX model. All
projects, config, copied plugins, tmux targets and artifacts are private to
--root. HOME/auth remain untouched. Never points at a production collection.

prepare --project NAME --python PATH [--uri URI] [--collection NAME]
start --project NAME --session NAME; screen/send/keys/stop --session NAME
collect --project NAME; refresh --project NAME
inspect --project NAME --label LABEL
replay-stop --project NAME; interrupt-worker --project NAME

The human/controlling agent interprets screens and authorizes UI interactions.
This helper does not guess whether an agent is finished or auto-approve menus.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]


def native_namespace(root):
    """Keep HOME/auth, redirect mutable CLI state without copying its contents.

    The original directory is only exposed read-only at an alias inside the
    mount namespace. Other original entries are passthrough symlinks; newly
    created settings, onboarding state and synthetic transcripts stay private.
    """
    original = Path.home() / ".gemini/antigravity-cli"
    state, alias = root / "native-state", root / "native-original"
    state.mkdir(exist_ok=True)
    alias.mkdir(exist_ok=True)
    mutable = {
        "settings.json",
        "onboarding.json",
        "state.json",
        "brain",
        "log",
        "logs",
        "crashes",
        "cache",
        "history",
        "history.json",
    }
    for entry in original.iterdir():
        target = state / entry.name
        if entry.name not in mutable and not target.exists() and not target.is_symlink():
            target.symlink_to(alias / entry.name, target_is_directory=entry.is_dir())
    for name in ("brain", "log", "logs", "crashes"):
        (state / name).mkdir(exist_ok=True)
    cache = state / "cache"
    cache.mkdir(exist_ok=True)
    if (original / "cache").is_dir():
        for entry in (original / "cache").iterdir():
            target = cache / entry.name
            if entry.name != "onboarding.json" and not target.exists() and not target.is_symlink():
                target.symlink_to(alias / "cache" / entry.name, target_is_directory=entry.is_dir())
    settings = state / "settings.json"
    if not settings.exists():
        settings.write_text("{}\n")
    return [
        "bwrap",
        "--bind",
        "/",
        "/",
        "--ro-bind",
        str(original),
        str(alias),
        "--bind",
        str(state),
        str(original),
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--",
    ]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tmux(root, *args, check=True, input=None):
    return subprocess.run(
        ["tmux", "-f", "/dev/null", "-S", str(root / "tmux.sock"), *args],
        input=input,
        capture_output=True,
        text=True,
        check=check,
    )


def environment(root, project):
    meta = json.loads((project / "harness.json").read_text())
    inherited = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "MEMSEARCH_DISABLE",
            "MEMSEARCH_AGY_HELPER",
            "MEMSEARCH_AGY_WORKER",
            "MEMSEARCH_DIR",
            "MEMSEARCH_AGY_BOOTSTRAPPED",
        )
    }
    return {
        **inherited,
        "PATH": str(project / ".harness/bin")
        + os.pathsep
        + str(Path(meta["python"]).parent)
        + os.pathsep
        + os.environ["PATH"],
        "PYTHONPATH": str(root / "isolation") + os.pathsep + str(Path(meta.get("source", SOURCE)) / "src"),
        "MEMSEARCH_E2E_CONFIG": str(project / ".harness/config.toml"),
        "MEMSEARCH_ANTIGRAVITY_SETTINGS": str(project / ".harness/settings.json"),
        "MEMSEARCH_E2E_PROJECT": str(project),
        "HF_HUB_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "AGY_CLI_DISABLE_AUTO_UPDATE": "1",
        "AGY_CLI_HIDE_ACCOUNT_INFO": "1",
    }


def refresh(project):
    meta = json.loads((project / "harness.json").read_text())
    source = Path(meta.get("source", SOURCE)) / "plugins/antigravity"
    target = project / ".agents/plugins/memsearch"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    hashes = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert all(hashlib.sha256((target / name).read_bytes()).hexdigest() == value for name, value in hashes.items())
    dump(project / "evidence/bundle-source.json", {"source": str(source), "copied_to": str(target), "sha256": hashes})


def isolation(root):
    (root / "isolation").mkdir(exist_ok=True)
    # Host command shells can reorder PATH. Restore the private wrapper before
    # bootstrap selects its interpreter, including in a stdlib-only Python.
    (root / "isolation/sitecustomize.py").write_text(
        "import os,sys,json,time\nfrom pathlib import Path\n"
        "project=os.environ.get('MEMSEARCH_E2E_PROJECT')\n"
        "if project:\n"
        " os.environ['PATH']=str(Path(project)/'.harness/bin')+os.pathsep+os.environ['PATH']\n"
        "if os.environ.get('MEMSEARCH_E2E_CONFIG'):\n"
        " try:\n"
        "  import memsearch.config\n"
        " except ModuleNotFoundError:\n"
        "  pass  # stdlib hook interpreter; bootstrap reexecs into the selected environment\n"
        " else:\n"
        "  memsearch.config.GLOBAL_CONFIG_PATH=Path(os.environ['MEMSEARCH_E2E_CONFIG'])\n"
        "  if project:\n"
        "   row={'at':time.time(),'pid':os.getpid(),'python':sys.executable,'entrypoint':sys.argv[0],'core':memsearch.config.__file__}\n"
        "   with (Path(project)/'evidence/interpreters.jsonl').open('a') as f:f.write(json.dumps(row)+'\\n')\n"
    )


def prepare(root, args):
    project = root / "projects" / args.project
    project.mkdir(parents=True, exist_ok=False)
    (project / ".harness/bin").mkdir(parents=True)
    isolation(root)
    python = str(Path(args.python or args.source / ".venv/bin/python").absolute())
    for name in ("python", "python3"):
        launcher = project / ".harness/bin" / name
        launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(python)} "$@"\n')
        launcher.chmod(0o755)
    wrapper = project / ".harness/bin/memsearch"
    wrapper.write_text(f"#!{python}\nfrom memsearch.cli import cli\ncli()\n")
    wrapper.chmod(0o755)
    uri = args.uri or str(project / ".harness/memory.db")
    config = f"[embedding]\nprovider = {json.dumps(args.embedding_provider)}\n\n[milvus]\nuri = {json.dumps(uri)}\n"
    if args.server_auth:
        config += 'token = "root:Milvus"\n'  # Public disposable test-server credential.
    if args.collection:
        if not args.collection.startswith("ms_agy_e2e_"):
            raise ValueError("Explicit collections must have the task-private ms_agy_e2e_ prefix")
        config += f"collection = {json.dumps(args.collection)}\n"
    config += '\n[plugins.antigravity.summarize]\nprovider = "native"\nmodel = ' + json.dumps(args.native_model) + "\n"
    (project / ".harness/config.toml").write_text(config)
    dump(
        project / ".harness/settings.json",
        {"permissions": {"allow": ["command(python3)", "command(memsearch)", "command(cat)", "command(pwd)"]}},
    )
    dump(
        project / "harness.json",
        {
            "project": str(project),
            "python": python,
            "uri": uri,
            "collection": args.collection,
            "auth": "public-test-server" if args.server_auth else "none",
            "source": str(args.source.resolve()),
            "agy": args.agy,
            "native_model": args.native_model,
        },
    )
    refresh(project)
    observer = project / ".agents/plugins/memsearch-e2e-observer"
    (observer / "scripts").mkdir(parents=True)
    dump(observer / "plugin.json", {"name": "memsearch-e2e-observer", "version": "0.1.0"})
    events = ["SessionStart", "PreInvocation", "Stop", "PostToolUse"]
    dump(
        observer / "hooks.json",
        {
            "evidence": {
                event: [{"type": "command", "command": f"python3 ./scripts/observe.py {event}", "timeout": 5}]
                if event != "PostToolUse"
                else [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {"type": "command", "command": f"python3 ./scripts/observe.py {event}", "timeout": 5}
                        ],
                    }
                ]
                for event in events
            }
        },
    )
    (observer / "scripts/observe.py").write_text(
        "import json, os, sys, time\nfrom pathlib import Path\n"
        "p=json.load(sys.stdin)\n"
        "keys=('conversationId','cwd','workspacePaths','transcriptPath','fullyIdle','terminationReason','executionNum','lastUserInput','toolCall')\n"
        "row={'event':sys.argv[1],'at':time.time(),'payload':{k:p[k] for k in keys if k in p}}\n"
        "path=Path(os.environ['MEMSEARCH_E2E_PROJECT'])/'evidence/hooks.jsonl'\npath.parent.mkdir(parents=True,exist_ok=True)\n"
        "with path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\\n')\n"
        "print('{}')\n"
    )
    env = environment(root, project)
    versions = subprocess.check_output(
        [
            python,
            "-c",
            "import json,sys,importlib.metadata as m,memsearch; print(json.dumps({'python':sys.executable,'core':memsearch.__file__,'versions':{n:m.version(n) for n in ('memsearch','milvus-lite','pymilvus','onnxruntime')}}))",
        ],
        env=env,
        text=True,
    )
    dump(project / "evidence/environment.json", json.loads(versions))
    return {"project": str(project), "environment": json.loads(versions)}


def collect(root, project):
    env = environment(root, project)
    meta = json.loads((project / "harness.json").read_text())
    events_path = project / "evidence/hooks.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
    transcripts = {
        e["payload"]["conversationId"]: e["payload"]["transcriptPath"]
        for e in events
        if e["payload"].get("transcriptPath")
    }
    code = """import json,sys
from dataclasses import asdict
import memsearch.transcript as transcript
# Preserve public tool results for evidence; thinking/system fields remain excluded.
transcript._clip = lambda text, *args: (text or '').strip()
print(json.dumps([asdict(t) for t in transcript.parse_transcript(sys.argv[1])],ensure_ascii=False))
"""
    for session, transcript in transcripts.items():
        turns = subprocess.check_output(
            [*native_namespace(root), meta["python"], "-c", code, transcript], env=env, text=True
        )
        dump(project / f"evidence/transcripts/{session}.json", {"source": transcript, "turns": json.loads(turns)})
    jobs = [json.loads(p.read_text()) for p in (project / ".memsearch/.antigravity/jobs").glob("*.json")]
    # Retry inputs may contain only spoken synthetic text, but need not be
    # duplicated in published evidence; originals remain in their own store.
    for job in jobs:
        job.pop("entries", None)
    dump(project / "evidence/jobs.json", jobs)
    memory = sorted((project / ".memsearch/memory").glob("*.md"))
    dump(project / "evidence/journals.json", {str(p): p.read_text() for p in memory})
    return {
        "sessions": list(transcripts),
        "jobs": len(jobs),
        "stages": [j["stage"] for j in jobs],
        "journals": len(memory),
    }


def replay_stop(root, project):
    """Replay an observed Stop, explicitly separate from native TUI evidence."""
    events = [json.loads(line) for line in (project / "evidence/hooks.jsonl").read_text().splitlines()]
    payload = next(e["payload"] for e in reversed(events) if e["event"] == "Stop")
    meta = json.loads((project / "harness.json").read_text())
    result = subprocess.run(
        [
            *native_namespace(root),
            meta["python"],
            str(project / ".agents/plugins/memsearch/scripts/runtime.py"),
            "stop",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        cwd=project,
        env=environment(root, project),
    )
    evidence = {
        "mode": "synthetic replay of actual observed Stop",
        "payload": payload,
        "result": json.loads(result.stdout),
    }
    dump(project / "evidence/replayed-stop.json", evidence)
    return evidence


def interrupt_worker(project):
    """Kill only the active worker recorded by this copied plugin and its children."""
    import psutil

    state = json.loads((project / ".memsearch/.antigravity/worker.json").read_text())
    if state["status"] != "running":
        raise ValueError("No active worker to interrupt")
    process = psutil.Process(state["pid"])
    expected = str(project / ".agents/plugins/memsearch/scripts/runtime.py")
    if expected not in process.cmdline() or Path(process.cwd()).resolve() != project.resolve():
        raise ValueError("Worker PID does not belong to this project's copied runtime")
    owned = [process, *process.children(recursive=True)]
    identities = [{"pid": p.pid, "created_at": p.create_time(), "name": p.name()} for p in owned]
    # Stop the parent first so it cannot spawn another helper during cleanup.
    process.suspend()
    for child in reversed(owned):
        with contextlib.suppress(psutil.NoSuchProcess):
            child.kill()
    _, alive = psutil.wait_procs(owned, timeout=3)
    evidence = {
        "mode": "deliberate process interruption",
        "worker": state,
        "processes": identities,
        "remaining_non_zombies": [p.pid for p in alive if p.status() != psutil.STATUS_ZOMBIE],
    }
    dump(project / "evidence/interrupted-worker.json", evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "prepare",
            "refresh",
            "start",
            "screen",
            "send",
            "keys",
            "stop",
            "collect",
            "inspect",
            "replay-stop",
            "interrupt-worker",
        ],
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project")
    parser.add_argument("--session")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--python")
    parser.add_argument("--agy", default=shutil.which("agy") or str(Path.home() / ".local/bin/agy"))
    parser.add_argument("--native-model", default="gemini-4-hydrogen-low")
    parser.add_argument("--embedding-provider", default="onnx")
    parser.add_argument("--uri")
    parser.add_argument("--collection")
    parser.add_argument("--server-auth", action="store_true")
    parser.add_argument("--text")
    parser.add_argument("--label", default="screen")
    parser.add_argument("--key", action="append", default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = root / "projects" / args.project if args.project else None
    session_path = root / "sessions" / f"{args.session}.json"
    if args.action == "prepare":
        result = prepare(root, args)
    elif args.action == "replay-stop":
        result = replay_stop(root, project)
    elif args.action == "interrupt-worker":
        result = interrupt_worker(project)
    elif args.action == "refresh":
        refresh(project)
        result = {"refreshed": str(project)}
    elif args.action == "start":
        if session_path.exists():
            raise ValueError("Session ownership record already exists; choose a new target name")
        env = environment(root, project)
        meta = json.loads((project / "harness.json").read_text())
        command = [
            *native_namespace(root),
            meta.get("agy", args.agy),
            "--model",
            meta.get("native_model", args.native_model),
            "--settings",
            str(project / ".harness/settings.json"),
        ]
        launch = project / ".harness" / f"launch-{args.session}.sh"
        exports = {
            k: env[k]
            for k in (
                "PATH",
                "PYTHONPATH",
                "MEMSEARCH_E2E_CONFIG",
                "MEMSEARCH_ANTIGRAVITY_SETTINGS",
                "MEMSEARCH_E2E_PROJECT",
                "HF_HUB_OFFLINE",
                "TOKENIZERS_PARALLELISM",
                "AGY_CLI_DISABLE_AUTO_UPDATE",
                "AGY_CLI_HIDE_ACCOUNT_INFO",
            )
        }
        launch.write_text(
            "#!/bin/sh\nunset MEMSEARCH_DISABLE MEMSEARCH_AGY_HELPER MEMSEARCH_AGY_WORKER MEMSEARCH_DIR MEMSEARCH_AGY_BOOTSTRAPPED\n"
            + "\n".join(f"export {k}={shlex.quote(v)}" for k, v in exports.items())
            + "\nexec "
            + shlex.join(command)
            + "\n"
        )
        result = tmux(
            root,
            "new-session",
            "-d",
            "-s",
            args.session,
            "-x",
            "150",
            "-y",
            "45",
            "-c",
            str(project),
            "sleep 30",
        )
        tmux(root, "set-option", "-w", "-t", "=" + args.session + ":0", "remain-on-exit", "on")
        tmux(
            root,
            "respawn-pane",
            "-k",
            "-t",
            "=" + args.session + ":0.0",
            "-c",
            str(project),
            "sh " + shlex.quote(str(launch)),
        )
        dump(
            session_path,
            {
                "name": args.session,
                "socket": str(root / "tmux.sock"),
                "project": str(project),
                "started_at": time.time(),
                "command": command,
            },
        )
        result = {"session": args.session, "socket": str(root / "tmux.sock")}
    else:
        if args.action == "inspect":
            env = environment(root, project)
            meta = json.loads((project / "harness.json").read_text())
            code = """import json,sys
from pathlib import Path
from pymilvus import MilvusClient
sys.path.insert(0,str(Path.cwd()/'.agents/plugins/memsearch/scripts'))
import runtime
p=Path.cwd();m=p/'.memsearch';cfg=runtime.config(p,m,runtime.collection(p,m))
c=MilvusClient(uri=cfg.milvus.uri,token=cfg.milvus.token)
try:
 if c.has_collection(cfg.milvus.collection): c.load_collection(cfg.milvus.collection)
 rows=c.query(collection_name=cfg.milvus.collection,filter='chunk_hash != ""',output_fields=['source','chunk_hash','content','heading','start_line','end_line'],consistency_level='Strong') if c.has_collection(cfg.milvus.collection) else []
 stats=c.get_collection_stats(cfg.milvus.collection) if c.has_collection(cfg.milvus.collection) else {}
 print(json.dumps({'collection':cfg.milvus.collection,'row_count':len(rows),'stats_without_explicit_flush':stats,'rows':rows},ensure_ascii=False))
finally:c.close()
"""
            result = subprocess.check_output(
                [*native_namespace(root), meta["python"], "-c", code], cwd=project, env=env, text=True
            )
            result = json.loads(result)
            dump(project / f"evidence/backend-{args.label}.json", result)
            result = {key: value for key, value in result.items() if key != "rows"}
        elif args.action == "collect":
            result = collect(root, project)
        else:
            owned = json.loads(session_path.read_text())
            target = "=" + owned["name"] + ":0.0"
            if args.action == "screen":
                screen = tmux(root, "capture-pane", "-p", "-t", target, "-S", "-180").stdout
                screen = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[account redacted]", screen)
                screen = re.sub(r"GCP Project: [^\n]+", "GCP Project: [redacted]", screen)
                path = Path(owned["project"]) / "evidence/screens" / f"{args.session}-{args.label}.txt"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(screen)
                result = {"screen": str(path), "text": screen}
            elif args.action == "send":
                tmux(root, "load-buffer", "-b", args.session, "-", input=args.text)
                tmux(root, "paste-buffer", "-p", "-b", args.session, "-t", target)
                time.sleep(0.2)
                tmux(root, "send-keys", "-t", target, "Enter")
                with (Path(owned["project"]) / "evidence/prompts.jsonl").open("a") as stream:
                    stream.write(json.dumps({"session": args.session, "at": time.time(), "prompt": args.text}) + "\n")
                result = {"sent": args.session}
            elif args.action == "keys":
                tmux(root, "send-keys", "-t", target, *args.key)
                result = {"keys": args.key, "session": args.session}
            else:
                # Exact task-owned target only; never touches the cc-use socket.
                import psutil

                pane = tmux(root, "display-message", "-p", "-t", target, "#{pane_pid}", check=False)
                processes = []
                if pane.returncode == 0:
                    with contextlib.suppress(psutil.NoSuchProcess, ValueError):
                        parent = psutil.Process(int(pane.stdout.strip()))
                        processes = [parent, *parent.children(recursive=True)]
                tmux(root, "kill-session", "-t", "=" + owned["name"], check=False)
                for process in reversed(processes):
                    with contextlib.suppress(psutil.NoSuchProcess):
                        if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                            process.kill()
                _, alive = psutil.wait_procs(processes, timeout=2)
                owned["stopped_at"] = time.time()
                owned["remaining_non_zombies"] = [p.pid for p in alive if p.status() != psutil.STATUS_ZOMBIE]
                dump(session_path, owned)
                result = {"stopped": args.session}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
