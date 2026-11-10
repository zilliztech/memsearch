"""Run the production maintenance entrypoint with a deterministic native LLM."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

if sys.argv[1] == "-c":
    # detectPythonCmd's interpreter availability probe, not a maintenance call.
    raise SystemExit(0)

if sys.argv[1] == "--prepare-index":
    from memsearch.index_state import record_index_started, resolve_index_state_path

    root = Path(sys.argv[2])
    memory = root / "memory"
    state = resolve_index_state_path([memory], memsearch_dir=root)
    record_index_started(state, operation="index", paths=[memory], collection="fixture", milvus_uri="fixture")
    assert state and state.is_file()
    sys.stdout.write(str(state) + "\n")
    raise SystemExit(0)

runner, *args = sys.argv[1:]
result = {"calls": []}
try:
    spec = importlib.util.spec_from_file_location("actual_maintenance_runner", runner)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fake_native(ctx, prompt):
        result["calls"].append(
            {
                "input_dir": str(ctx.input_dir),
                "has_journal": "JOURNAL_SENTINEL_832" in prompt,
            }
        )
        return json.dumps({"action": "replace", "content": "Checked fixture memory."})

    # Keep CLI parsing, configuration, run_due_tasks, and file persistence real.
    module.run_native_provider = fake_native
    sys.argv = [runner, *args]
    result["exit"] = module.main()
except Exception:
    result["error"] = traceback.format_exc()
    result["exit"] = 1
finally:
    done = Path(os.environ["MAINTENANCE_TEST_DONE"])
    temporary = done.with_suffix(".tmp")
    temporary.write_text(json.dumps(result), encoding="utf-8")
    temporary.replace(done)
raise SystemExit(result["exit"])
