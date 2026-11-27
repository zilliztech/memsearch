#!/usr/bin/env python3
"""Opt-in real Lite index/recall contention across two harness workspaces.

Both projects must already use the same disposable local URI and an explicitly
shared collection. The index uses real core work, then a test-only gate delays
return while its DB client remains open. The other process runs real scoped
recall during that interval. No model/embedding/backend result is mocked.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from antigravity_e2e import dump, environment

INDEX = """import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'.agents/plugins/memsearch/scripts'))
import runtime
from memsearch import MemSearch
p=Path.cwd();m=p/'.memsearch';cfg=runtime.config(p,m,runtime.collection(p,m))
assert not cfg.milvus.uri.startswith(('http','tcp','unix:'))
original=MemSearch.index_with_report
gate=Path(sys.argv[1]);release=Path(sys.argv[2])
async def gated(self,*args,**kwargs):
 report=await original(self,*args,**kwargs)
 gate.write_text(json.dumps({'at':time.time(),'uri':str(Path(cfg.milvus.uri).expanduser().resolve()),'collection':cfg.milvus.collection}))
 deadline=time.monotonic()+25
 while not release.exists():
  if time.monotonic()>deadline:raise RuntimeError('test gate expired')
  await asyncio.sleep(.05)
 return report
MemSearch.index_with_report=gated
runtime.run_index(m,cfg)
print(json.dumps({'index':'ok','finished_at':time.time()}))
"""

READER = """import contextlib,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'.agents/plugins/memsearch/scripts'))
import runtime
attempt,acquired=map(Path,sys.argv[1:3]);sys.argv=sys.argv[:1]+sys.argv[3:]
normal=runtime.local_db_access
@contextlib.contextmanager
def traced(uri):
 attempt.write_text(json.dumps({'at':time.time(),'uri':str(Path(uri).expanduser().resolve())}))
 with normal(uri):
  acquired.write_text(json.dumps({'at':time.time()}))
  yield
runtime.local_db_access=traced
raise SystemExit(runtime.main())
"""

BUSY = """import json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'.agents/plugins/memsearch/scripts'))
import runtime
from filelock import FileLock
p=Path.cwd();m=p/'.memsearch';cfg=runtime.config(p,m,runtime.collection(p,m))
database=Path(cfg.milvus.uri).expanduser().resolve()
normal=runtime.local_db_access
runtime.local_db_access=lambda uri:normal(uri,timeout=.1)
with FileLock(str(database)+'.antigravity.lock'):
 try:runtime.run_index(m,cfg)
 except runtime.LocalDatabaseBusy:pass
 else:raise AssertionError('Expected a bounded busy failure')
 failed=json.loads((m/'.index-state.json').read_text())
 assert failed['status']=='error'
runtime.local_db_access=normal
runtime.run_index(m,cfg)
recovered=json.loads((m/'.index-state.json').read_text())
assert recovered['status']=='ok'
print(json.dumps({'busy_state':failed,'recovered_state':recovered}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--peer", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--label", default="lite-contention")
    args = parser.parse_args()
    root = args.root.resolve()
    project, peer = [root / "projects" / name for name in (args.project, args.peer)]
    assert project != peer
    meta, peer_meta = [json.loads((p / "harness.json").read_text()) for p in (project, peer)]
    evidence = project / "evidence"
    gate, release, attempt, acquired = [
        evidence / f"{args.label}-{name}" for name in ("ready", "release", "attempt", "acquired")
    ]
    for path in (gate, release, attempt, acquired):
        path.unlink(missing_ok=True)
    writer = subprocess.Popen(
        [meta["python"], "-c", INDEX, str(gate), str(release)],
        cwd=project,
        env=environment(root, project),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    reader = None
    try:
        deadline = time.monotonic() + 30
        while not gate.exists():
            if writer.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Index did not reach the test gate")
            time.sleep(0.05)
        started = time.time()
        reader = subprocess.Popen(
            [
                peer_meta["python"],
                "-c",
                READER,
                str(attempt),
                str(acquired),
                "cli",
                "--project-dir",
                str(peer),
                "--",
                "search",
                args.query,
                "-j",
            ],
            cwd=peer,
            env=environment(root, peer),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 15
        while not attempt.exists():
            if reader.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Reader did not attempt the URI lock")
            time.sleep(0.05)
        time.sleep(0.3)
        assert reader.poll() is None and not acquired.exists(), (
            "Recall must wait while the index client owns the shared local URI"
        )
        released = time.time()
        release.touch()
        index_output, _ = writer.communicate(timeout=30)
        recall_output, _ = reader.communicate(timeout=30)
        assert writer.returncode == reader.returncode == 0
        lock_attempt, lock_acquired = json.loads(attempt.read_text()), json.loads(acquired.read_text())
        assert lock_acquired["at"] >= released and lock_acquired["at"] - lock_attempt["at"] >= 0.3
        assert lock_attempt["uri"] == json.loads(gate.read_text())["uri"]
        hits = json.loads(recall_output)
        assert hits and any(args.query in hit["content"] for hit in hits)
        busy = subprocess.check_output(
            [meta["python"], "-c", BUSY], cwd=project, env=environment(root, project), text=True
        )
        result = {
            "mode": "actual index and recall; deterministic test gate holds the index DB client before close",
            "project": str(project),
            "peer": str(peer),
            "gate": json.loads(gate.read_text()),
            "recall_started_at": started,
            "gate_released_at": released,
            "recall_waited": True,
            "lock_attempt": lock_attempt,
            "lock_acquired": lock_acquired,
            "index": json.loads(index_output),
            "hits": hits,
            "busy_recovery": json.loads(busy),
        }
        dump(evidence / f"{args.label}.json", result)
        print(json.dumps({"status": "passed", "evidence": str(evidence / f"{args.label}.json")}))
    finally:
        release.touch()
        for process in (writer, reader):
            if process is not None and process.poll() is None:
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    import psutil

                    owned = psutil.Process(process.pid)
                    for child in owned.children(recursive=True):
                        child.kill()
                    owned.kill()
                    process.communicate(timeout=5)


if __name__ == "__main__":
    main()
