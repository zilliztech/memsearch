from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.opencode_v2_fixtures import Fixture, capture, reader


@pytest.fixture
def fixture(tmp_path):
    value = Fixture(tmp_path / "project")
    yield value
    value.conn.close()


@pytest.fixture
def store(fixture):
    with contextlib.closing(capture.CaptureStore(str(fixture.root))) as value:
        yield value


def test_sparse_seq_is_order_not_timestamps(fixture, store):
    fixture.turn()
    fixture.turn(40)
    source, count = fixture.batch(store)
    assert count == 2
    assert store.cursor(source, "session") == 55
    assert fixture.journals().count("<!-- session:session turn:") == 2
    assert fixture.batch(store)[1] == 0
    assert "synthetic user marker" not in fixture.journals()


@pytest.mark.parametrize(
    "completed,tools,finish,retry,expected",
    [
        (False, [], "stop", None, "pending"),
        (True, ["running"], "stop", None, "pending"),
        (True, ["pending"], "stop", None, "pending"),
        (True, ["completed", "error"], "stop", None, "complete"),
        (True, [], "tool-calls", None, "pending"),
        (True, [], "stop", {"attempt": 1}, "pending"),
    ],
)
def test_completed_and_all_tools_settled(fixture, completed, tools, finish, retry, expected):
    fixture.user()
    fixture.assistant(completed=completed, tools=tools, finish=finish, retry=retry)
    fixture.idle()
    turn = reader.build_turns(fixture.conn, "session")[0]
    assert turn.status == expected
    assert "RAW_TOOL_SECRET" not in turn.render()


def test_streamed_update_and_missed_event_recovered(fixture, store):
    fixture.user()
    fixture.assistant(completed=False)
    fixture.idle()
    assert fixture.batch(store)[1] == 0
    data = json.loads(fixture.conn.execute("SELECT data FROM session_message WHERE seq=9").fetchone()[0])
    data["time"]["completed"] = 5
    fixture.conn.execute("UPDATE session_message SET data=? WHERE seq=9", (json.dumps(data),))
    fixture.conn.commit()
    assert fixture.batch(store)[1] == 1


def test_textless_steps_and_synthetic_rows(fixture):
    fixture.user()
    fixture.row(4, "synthetic", {"text": "RAW_SYNTHETIC"})
    fixture.assistant(seq=5, tools=["completed"], finish="tool-calls", text="")
    fixture.row(6, "compaction", {"summary": "RAW_COMPACTION"})
    fixture.assistant()
    fixture.idle()
    turn = reader.build_turns(fixture.conn, "session")[0]
    assert turn.status == "complete"
    assert len(turn.messages) == 3
    assert "RAW_" not in turn.render()


def test_pending_does_not_skip_later_turns(fixture, store):
    fixture.user()
    fixture.assistant(completed=False, tools=["running"])
    fixture.user(11)
    fixture.assistant(12)
    fixture.idle()
    source, count = fixture.batch(store)
    assert count == 0
    assert store.cursor(source, "session") == -1


def test_steered_intent_does_not_block_completed_response(fixture, store):
    fixture.user()
    fixture.user(6)
    fixture.assistant()
    fixture.idle()
    assert [t.status for t in reader.build_turns(fixture.conn, "session")] == ["discarded", "complete"]
    assert fixture.batch(store)[1] == 1
    assert "turn:msg6" in fixture.journals()


@pytest.mark.parametrize("outcome", ["failed", "interrupted"])
def test_terminal_failure_advances_without_summary(fixture, store, outcome):
    fixture.user()
    fixture.assistant(completed=False)
    fixture.idle(outcome=outcome)
    source, count = fixture.batch(store, lambda _: pytest.fail("not complete"))
    assert count == 0
    assert store.cursor(source, "session") == 15


def test_shutdown_without_idle_resumes_same_turn(fixture, store):
    fixture.user()
    fixture.assistant()
    assert fixture.batch(store)[1] == 0
    fixture.idle()
    assert fixture.batch(store)[1] == 1


def test_first_activation_baselines_only_settled_history(fixture, store):
    fixture.turn()
    fixture.user(22)
    fixture.assistant(29)
    assert fixture.batch(store, initialize=True)[1] == 0
    fixture.idle(35)
    assert fixture.batch(store)[1] == 1
    assert "turn:msg2 " not in fixture.journals()
    assert "turn:msg22 " in fixture.journals()


def test_baseline_transaction_rolls_back_on_bad_history(fixture, store):
    fixture.turn()
    fixture.session("z")
    fixture.row(1, "user", [], session="z")
    with pytest.raises(reader.TranscriptError):
        fixture.batch(store, initialize=True)
    assert store.db.execute("SELECT count(*) FROM v2_sources").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM v2_sessions").fetchone()[0] == 0


def test_cancel_leaves_pending_and_restart_summarizes_once(fixture, store):
    fixture.turn()

    def cancelled(_):
        raise capture.Cancelled()

    with pytest.raises(capture.Cancelled):
        fixture.batch(store, cancelled)
    assert store.db.execute("SELECT entry FROM v2_pending").fetchone()[0] is None
    assert fixture.journals() == ""
    assert fixture.batch(store)[1] == 1
    assert store.db.execute("SELECT count(*) FROM v2_pending").fetchone()[0] == 0


def test_append_survives_checkpoint_failure_without_repeat(fixture, store, monkeypatch):
    fixture.turn()
    original = store.commit
    monkeypatch.setattr(store, "commit", lambda *_: (_ for _ in ()).throw(OSError("checkpoint fault")))
    with pytest.raises(OSError):
        fixture.batch(store)
    before = fixture.journals()
    monkeypatch.setattr(store, "commit", original)
    assert fixture.batch(store, lambda _: pytest.fail("prepared summary must be reused"))[1] == 1
    assert fixture.journals() == before


def test_partial_append_is_completed_not_accepted_by_anchor(fixture, store, monkeypatch):
    fixture.turn()
    original = store.append_prepared

    def partial(row):
        # The anchor is present, but the summary is not yet complete.
        entry = bytes(row["entry"])
        Path(row["journal"]).write_bytes(entry[: entry.index(b"- Safe") + 3])
        raise OSError("disk fault")

    monkeypatch.setattr(store, "append_prepared", partial)
    with pytest.raises(OSError):
        fixture.batch(store)
    monkeypatch.setattr(store, "append_prepared", original)
    assert fixture.batch(store, lambda _: pytest.fail("already prepared"))[1] == 1
    assert fixture.journals().count("<!-- session:") == 1
    assert fixture.journals().endswith("- Safe summary.\n\n")


def test_concurrent_journal_edit_fails_closed(fixture, store, monkeypatch):
    fixture.turn()
    original = store.append_prepared

    def conflict(row):
        Path(row["journal"]).write_text("UNRELATED JOURNAL EDIT")
        original(row)

    monkeypatch.setattr(store, "append_prepared", conflict)
    with pytest.raises(RuntimeError, match="Journal changed"):
        fixture.batch(store)
    assert fixture.journals() == "UNRELATED JOURNAL EDIT"
    assert store.db.execute("SELECT count(*) FROM v2_pending").fetchone()[0] == 1


def test_existing_anchors_and_legacy_sidecar_preserved(fixture, store):
    fixture.turn()
    store.memory.mkdir()
    original = "# Existing\n<!-- session:session turn:msg2 db:/old/db -->\n- Kept.\n"
    (store.memory / "2025-01-02.md").write_text(original)
    store.db.execute("CREATE TABLE legacy_checkpoint(time INTEGER)")
    store.db.execute("INSERT INTO legacy_checkpoint VALUES(123456789)")
    store.db.commit()
    assert fixture.batch(store, lambda _: pytest.fail("existing journal"))[1] == 0
    assert fixture.journals() == original
    assert store.db.execute("SELECT time FROM legacy_checkpoint").fetchone()[0] == 123456789


def test_disabled_retains_pending_without_model_call(fixture, store):
    fixture.turn()
    assert fixture.batch(store, lambda _: pytest.fail("disabled"), enabled=False)[1] == 0
    assert fixture.batch(store)[1] == 1


def test_exact_project_workspace_and_subagent_ownership(fixture, store, tmp_path):
    sibling = tmp_path / "elsewhere/project"
    sibling.mkdir(parents=True)
    for name, kwargs in [
        ("reidentified", {"project": "other"}),
        ("workspace", {"workspace": "ws"}),
        ("subagent", {"parent": "session"}),
        ("same_name", {"directory": sibling}),
    ]:
        fixture.session(name, **kwargs)
        fixture.turn(session=name)
    fixture.turn()
    assert reader.session_ids(fixture.conn, fixture.scope) == ["reidentified", "session"]
    assert fixture.batch(store)[1] == 2


def test_git_subdirectory_owned_but_worktree_separate(fixture, tmp_path):
    subprocess.run(["git", "init", "-q", str(fixture.root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(fixture.root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    sub = fixture.root / "nested"
    sub.mkdir()
    other = tmp_path / "worktree"
    subprocess.run(
        ["git", "-C", str(fixture.root), "worktree", "add", "--detach", str(other)], check=True, capture_output=True
    )
    fixture.session("nested", directory=sub)
    fixture.session("worktree", directory=other)
    nested_repo = fixture.root / "separate-repo"
    subprocess.run(["git", "init", "-q", str(nested_repo)], check=True)
    fixture.session("nested-repo", directory=nested_repo)
    alias = tmp_path / "alias"
    alias.symlink_to(sub, target_is_directory=True)
    fixture.session("alias", directory=alias, project="different-id")
    assert reader.session_ids(fixture.conn, fixture.scope) == ["alias", "nested", "session"]


def test_foreign_payload_is_never_selected(fixture, store, tmp_path):
    from tests.opencode_v2_fixtures import parser

    other = tmp_path / "other"
    other.mkdir()
    fixture.session("foreign", directory=other)
    fixture.row(0, "user", [], session="foreign")
    fixture.turn()
    queries = []
    fixture.conn.set_trace_callback(queries.append)
    assert fixture.batch(store)[1] == 1
    assert not any("data FROM session_message" in q and "'foreign'" in q for q in queries)
    with pytest.raises(reader.TranscriptError, match="outside"):
        parser.parse_session("foreign", fixture.scope, str(fixture.path))


def test_move_never_decodes_prior_location_payload(fixture, store):
    fixture.row(0, "user", [])
    fixture.row(20, "location-switched", {"directory": str(fixture.root)})
    fixture.turn(30)
    assert fixture.batch(store)[1] == 1


def test_project_reidentification_preserves_pending_and_cursor(fixture, store):
    fixture.turn()
    with pytest.raises(capture.Cancelled):
        fixture.batch(store, lambda _: (_ for _ in ()).throw(capture.Cancelled()))
    old_key = capture.source_key(str(fixture.path), fixture.scope)
    fixture.scope = reader.Scope(str(fixture.root), "new-host-id")
    assert capture.source_key(str(fixture.path), fixture.scope) == old_key
    assert fixture.batch(store, initialize=True)[1] == 0
    assert fixture.batch(store)[1] == 1
    fixture.scope = reader.Scope(str(fixture.root), "another-host-id")
    assert fixture.batch(store)[1] == 0
    assert fixture.journals().count("<!-- session:") == 1


def test_move_excludes_old_location_history(fixture, store):
    fixture.turn()
    fixture.row(20, "location-switched", {"directory": str(fixture.root)})
    fixture.turn(30)
    assert fixture.batch(store)[1] == 1
    assert "turn:msg2 " not in fixture.journals()


@pytest.mark.parametrize("parent_present", [True, False])
def test_fork_skips_copied_history_but_keeps_new_turn(fixture, store, parent_present):
    fixture.turn()
    fixture.session("fork", fork="session", boundary={"type": "after", "messageID": "msg9"})
    fixture.user(session="fork", id="msg_fork_2")
    fixture.row(
        9,
        "assistant",
        {"content": [{"type": "text", "text": "copied"}], "finish": "stop", "time": {"completed": 1}},
        session="fork",
        id="msg_fork_9",
    )
    fixture.turn(30, session="fork")
    if not parent_present:
        fixture.conn.execute("DELETE FROM session_message WHERE session_id='session'")
        fixture.conn.execute("DELETE FROM session_v2 WHERE id='session'")
        fixture.conn.commit()
    fixture.batch(store)
    assert "turn:msg_fork_2" not in fixture.journals()
    assert "session:fork turn:msg32" in fixture.journals()


def test_two_capture_instances_serialize_real_writes(fixture):
    fixture.turn()

    def worker():
        with (
            contextlib.closing(reader.open_source(str(fixture.path))) as conn,
            contextlib.closing(capture.CaptureStore(str(fixture.root))) as store,
        ):
            return capture.capture_batch(conn, store, fixture.scope, str(fixture.path), lambda _: "- Concurrent.")[1]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: worker(), range(2))) == [0, 1]
    assert fixture.journals().count("<!-- session:") == 1


def test_native_custom_prompt_bullet_validation_and_failure(fixture, tmp_path):
    from memsearch.config import MemSearchConfig

    cfg = MemSearchConfig()
    custom = tmp_path / "prompt.txt"
    custom.write_text("CUSTOM {{AGENT_NAME}}", encoding="utf8")
    cfg.prompts.summarize = str(custom)
    cfg.plugins.opencode.summarize.model = "openai/title"
    fixture.turn()
    turn = reader.build_turns(fixture.conn, "session")[0]

    def native(prompt, model, task):
        assert prompt.startswith("CUSTOM OpenCode\n")
        assert model == "openai/title" and task == "summarize"
        return "preamble\n- 中文摘要\nnoise"

    assert capture.summarize(turn, cfg, [], str(fixture.root), native) == "- 中文摘要"
    assert capture.summarize(turn, cfg, [], str(fixture.root), lambda *_: "raw text") == capture.UNAVAILABLE
    assert (
        capture.summarize(
            turn, cfg, [], str(fixture.root), lambda *_: (_ for _ in ()).throw(ValueError("RAW_PRIVATE_ERROR"))
        )
        == capture.UNAVAILABLE
    )


@pytest.mark.parametrize(
    "response,expected",
    [
        ("Plain 中文 summary", "Plain 中文 summary"),
        ("Preamble\n- 中文 summary\nTrailing text", "- 中文 summary"),
    ],
)
def test_managed_summary_preserves_plain_utf8_and_argv(fixture, tmp_path, response, expected):
    from memsearch.config import MemSearchConfig

    cfg = MemSearchConfig()
    cfg.plugins.opencode.summarize.provider = " custom-provider "
    fixture.turn(text="中文 marker")
    turn = reader.build_turns(fixture.conn, "session")[0]
    cli = tmp_path / "cli with spaces.py"
    cli.write_text(
        f"import sys\nassert sys.argv[1:] == ['summarize','--plugin','opencode','--agent-name','OpenCode']\nassert '中文 marker' in sys.stdin.read()\nprint({response!r})\n"
    )
    assert (
        capture.summarize(turn, cfg, [sys.executable, str(cli)], str(fixture.root), lambda *_: pytest.fail("native"))
        == expected
    )


def test_transcript_and_summary_size_bounds(fixture):
    fixture.user(text="x" * 100000)
    for i in range(3, 13):
        fixture.assistant(i, text="y" * 10000, finish="tool-calls")
    fixture.assistant(14)
    fixture.idle()
    turn = reader.build_turns(fixture.conn, "session")[0]
    assert len(turn.render()) <= 24000
    from memsearch.config import MemSearchConfig

    assert (
        capture.summarize(turn, MemSearchConfig(), [], str(fixture.root), lambda *_: "- " + "x" * 20000)
        == capture.UNAVAILABLE
    )


def test_move_during_inference_cannot_append_to_old_project(fixture, store, tmp_path):
    fixture.turn()
    other = tmp_path / "moved"
    other.mkdir()

    def summarize_and_move(_):
        fixture.conn.execute("UPDATE session_v2 SET directory=? WHERE id='session'", (str(other),))
        fixture.conn.commit()
        return "- Wrong owner's summary."

    with pytest.raises(reader.TranscriptError, match="outside"):
        fixture.batch(store, summarize_and_move)
    assert fixture.journals() == ""
    assert store.db.execute("SELECT count(*) FROM v2_pending").fetchone()[0] == 1


def test_native_eof_and_host_cancellation_are_retryable(monkeypatch):
    import io

    for reply in ["", '{"cancelled":true}\n']:
        monkeypatch.setattr(capture.sys, "stdin", io.StringIO(reply))
        monkeypatch.setattr(capture.sys, "stdout", io.StringIO())
        with pytest.raises(capture.Cancelled):
            capture.native_request("synthetic prompt")


def test_fork_before_sparse_boundary_does_not_skip_new_child_turn(fixture, store):
    fixture.turn()
    fixture.user(100)
    fixture.session("fork", fork="session", boundary={"type": "before", "messageID": "msg100"})
    fixture.user(session="fork", id="msg_fork_2")
    fixture.row(15, "idle", {"outcome": "succeeded"}, session="fork", id="msg_fork_15")
    fixture.turn(20, session="fork")
    fixture.batch(store)
    assert "session:fork turn:msg22" in fixture.journals()
    assert "turn:msg_fork_2" not in fixture.journals()


def test_index_failure_retries_index_without_resummarizing_or_appending(fixture, tmp_path):
    import os

    from tests.opencode_v2_fixtures import SCRIPTS

    fixture.turn()
    home = tmp_path / "isolated-home"
    home.mkdir()
    cli = tmp_path / "index-cli.py"
    cli.write_text(
        "from pathlib import Path\nimport sys\n"
        "assert sys.argv[1] == 'index'\n"
        "assert '--default-collection' in sys.argv\n"
        "Path('index-attempts').open('a').write('attempt\\n')\n"
        "sys.exit(0 if Path('index-ready').exists() else 1)\n"
    )
    argv = [
        sys.executable,
        str(SCRIPTS / "capture.py"),
        "--project-dir",
        str(fixture.root),
        "--project-id",
        "project",
        "--db",
        str(fixture.path),
        "--collection",
        "fixture-collection",
        "--command",
        json.dumps([sys.executable, str(cli)]),
    ]
    env = {**os.environ, "HOME": str(home), "MEMSEARCH_DIR": str(fixture.root / ".memsearch")}
    first = subprocess.run(
        argv, input='{"text":"- Durable fixture summary."}\n', text=True, capture_output=True, env=env, timeout=20
    )
    assert first.returncode == 1, first.stderr
    assert '"type": "generate"' in first.stdout
    before = fixture.journals()
    assert "Durable fixture summary" in before
    (fixture.root / "index-ready").touch()
    second = subprocess.run(argv, input="", text=True, capture_output=True, env=env, timeout=20)
    assert second.returncode == 0, second.stdout + second.stderr
    assert '"type": "generate"' not in second.stdout
    assert fixture.journals() == before
    assert (fixture.root / "index-attempts").read_text().count("attempt") == 2
    with contextlib.closing(capture.CaptureStore(str(fixture.root))) as store:
        assert store.db.execute("SELECT index_dirty FROM v2_sources").fetchone()[0] == 0


def test_disabled_helper_does_not_request_inference(fixture, tmp_path):
    import os

    from tests.opencode_v2_fixtures import SCRIPTS

    fixture.turn()
    home = tmp_path / "home"
    (home / ".memsearch").mkdir(parents=True)
    (home / ".memsearch/config.toml").write_text("[plugins.opencode.summarize]\nenabled = false\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "capture.py"),
            "--project-dir",
            str(fixture.root),
            "--project-id",
            "project",
            "--db",
            str(fixture.path),
            "--collection",
            "fixture",
            "--command",
            json.dumps(["unused"]),
        ],
        input="",
        text=True,
        capture_output=True,
        timeout=20,
        env={**os.environ, "HOME": str(home), "MEMSEARCH_DIR": str(fixture.root / ".memsearch")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"type": "generate"' not in result.stdout
    assert fixture.journals() == ""


def test_sigterm_during_native_request_replays_from_durable_pending(fixture, tmp_path):
    import os
    import selectors

    from tests.opencode_v2_fixtures import SCRIPTS

    fixture.turn()
    home = tmp_path / "home"
    home.mkdir()
    cli = tmp_path / "index.py"
    cli.write_text("import sys\nassert sys.argv[1] == 'index'\n")
    argv = [
        sys.executable,
        str(SCRIPTS / "capture.py"),
        "--project-dir",
        str(fixture.root),
        "--project-id",
        "project",
        "--db",
        str(fixture.path),
        "--collection",
        "fixture",
        "--command",
        json.dumps([sys.executable, str(cli)]),
    ]
    env = {**os.environ, "HOME": str(home), "MEMSEARCH_DIR": str(fixture.root / ".memsearch")}
    with subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    ) as process:
        try:
            with selectors.DefaultSelector() as ready:
                ready.register(process.stdout, selectors.EVENT_READ)
                assert ready.select(10), "helper did not request native generation"
            assert json.loads(process.stdout.readline())["type"] == "generate"
            process.terminate()
            assert process.wait(timeout=5) == 75
        finally:
            if process.poll() is None:
                process.kill()
    assert fixture.journals() == ""
    with contextlib.closing(capture.CaptureStore(str(fixture.root))) as store:
        assert store.db.execute("SELECT entry FROM v2_pending").fetchone()[0] is None
    result = subprocess.run(
        argv, input='{"text":"- Recovered after shutdown."}\n', text=True, capture_output=True, env=env, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert fixture.journals().count("Recovered after shutdown") == 1


def load_migrated_projection(fixture):
    """Use the exact V2 rows from the outer official migration reproduction."""
    data = json.loads((Path(__file__).parent / "fixtures/opencode-v2-migrated.json").read_text())
    session_id = data["session_id"]
    fixture.session(session_id, project=data["stored_project_id"])
    fixture.scope = reader.Scope(str(fixture.root), data["requester_project_id"])
    for row in data["messages"]:
        fixture.row(row["seq"], row["type"], row["data"], session=session_id, id=row["id"])
    return session_id, data["messages"][0]["id"]


@pytest.mark.parametrize("existing_anchor", [True, False])
def test_official_migrated_shape_baselines_and_continues_without_idle(fixture, store, existing_anchor):
    from tests.opencode_v2_fixtures import parser

    session_id, turn_id = load_migrated_projection(fixture)
    assert fixture.conn.execute("SELECT count(*) FROM session_message WHERE type='idle'").fetchone()[0] == 0
    anchor = f"<!-- session:{session_id} turn:{turn_id} db:/original/opencode.db -->"
    original = "# Existing migration journal\n" + anchor + "\n- Preserved summary.\n"
    store.memory.mkdir(exist_ok=True)
    journal = store.memory / "2026-01-01.md"
    if existing_anchor:
        journal.write_text(original)
    text = parser.parse_session(session_id, fixture.scope, str(fixture.path), turn_id=turn_id, context=0)
    assert "cedar-8174" in text and "23-hour" in text
    source, count = fixture.batch(store, lambda _: pytest.fail("historical baseline"), initialize=True)
    assert count == 0 and store.cursor(source, session_id) == 1
    fixture.user(20, session=session_id)
    fixture.assistant(29, session=session_id)
    assert fixture.batch(store)[1] == 0  # Live settled step still awaits its idle boundary.
    fixture.idle(35, session=session_id)
    assert fixture.batch(store)[1] == 1
    assert fixture.batch(store)[1] == 0
    assert fixture.journals().count(f"session:{session_id} turn:msg20") == 1
    if existing_anchor:
        assert journal.read_text() == original
    else:
        assert turn_id not in fixture.journals()


def test_migrated_anchor_replay_and_cancelled_v2_continuation(fixture, store):
    session_id, turn_id = load_migrated_projection(fixture)
    store.memory.mkdir()
    journal = store.memory / "2026-01-01.md"
    original = f"# Existing\n<!-- session:{session_id} turn:{turn_id} db:/original/opencode.db -->\n- Kept.\n"
    journal.write_text(original)
    fixture.turn(20, session=session_id)
    with pytest.raises(capture.Cancelled):
        fixture.batch(store, lambda _: (_ for _ in ()).throw(capture.Cancelled()))
    assert store.cursor(capture.source_key(str(fixture.path), fixture.scope), session_id) == 1
    # A new plugin activation marks index dirty; normal replay reuses pending work.
    assert fixture.batch(store, initialize=True)[1] == 0
    assert fixture.batch(store)[1] == 1
    assert fixture.batch(store)[1] == 0
    assert journal.read_text() == original
    assert fixture.journals().count(f"session:{session_id} turn:msg22") == 1


def test_later_failed_execution_does_not_change_imported_settled_history(fixture):
    session_id, _ = load_migrated_projection(fixture)
    fixture.user(20, session=session_id)
    fixture.assistant(29, session=session_id, completed=False)
    fixture.idle(35, session=session_id, outcome="failed")
    turns = reader.build_turns(fixture.conn, session_id)
    assert [turn.status for turn in turns] == ["complete", "discarded"]


def test_queued_user_does_not_prove_live_completion(fixture, store):
    fixture.user()
    fixture.assistant()
    fixture.user(20)
    assert [turn.status for turn in reader.build_turns(fixture.conn, "session")] == ["pending", "pending"]
    assert fixture.batch(store)[1] == 0
    fixture.assistant(29)
    fixture.idle(35)
    assert fixture.batch(store)[1] == 2


@pytest.mark.parametrize("mutation", ["partial", "retry", "error", "unsettled-tool"])
def test_imported_shape_never_promotes_partial_retry_error_or_unsettled_tools(fixture, store, mutation):
    session_id, _ = load_migrated_projection(fixture)
    row = fixture.conn.execute(
        "SELECT id,data FROM session_message WHERE session_id=? AND type='assistant'", (session_id,)
    ).fetchone()
    data = json.loads(row["data"])
    if mutation == "partial":
        del data["time"]["completed"]
    elif mutation == "retry":
        data["retry"] = {"attempt": 1}
    elif mutation == "error":
        data["error"] = {"type": "provider.error", "message": "failed despite stop"}
    else:
        data["content"].append({"type": "tool", "state": {"status": "running"}})
    fixture.conn.execute("UPDATE session_message SET data=? WHERE id=?", (json.dumps(data), row["id"]))
    fixture.conn.commit()
    fixture.user(20, session=session_id)
    assert reader.build_turns(fixture.conn, session_id)[0].status == "pending"
    source, count = fixture.batch(store, initialize=True)
    assert count == 0 and store.cursor(source, session_id) == -1


def test_final_assistant_error_is_not_success_but_recovered_retry_is(fixture, store):
    fixture.user()
    fixture.assistant(retry={"attempt": 1})
    fixture.idle()
    row = fixture.conn.execute("SELECT data FROM session_message WHERE seq=9").fetchone()
    data = json.loads(row[0])
    data["error"] = {"type": "provider.error", "message": "temporary failure"}
    fixture.conn.execute("UPDATE session_message SET data=? WHERE seq=9", (json.dumps(data),))
    fixture.conn.commit()
    assert fixture.batch(store)[1] == 0
    data.pop("retry")
    fixture.conn.execute("UPDATE session_message SET data=? WHERE seq=9", (json.dumps(data),))
    fixture.conn.commit()
    assert reader.build_turns(fixture.conn, "session")[0].status == "discarded"
    # The host clears retry/error when the same assistant starts again.
    data.pop("error")
    fixture.conn.execute("UPDATE session_message SET data=? WHERE seq=9", (json.dumps(data),))
    fixture.conn.commit()
    assert fixture.batch(store)[1] == 1


def test_successful_final_response_after_an_earlier_failed_attempt(fixture, store):
    fixture.user()
    fixture.row(
        5,
        "assistant",
        {"time": {"created": 1, "completed": 2}, "content": [], "finish": "error", "error": {"type": "provider.error"}},
    )
    fixture.assistant()
    fixture.idle()
    assert fixture.batch(store)[1] == 1


def test_maintenance_only_helper_never_enters_capture_lock_or_database(fixture, store, tmp_path):
    import os

    from tests.opencode_v2_fixtures import SCRIPTS

    home = tmp_path / "home"
    home.mkdir()
    # The fixture holds the capture lock. The optional helper must still finish.
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "capture.py"),
            "--maintenance",
            "--project-dir",
            str(fixture.root),
            "--project-id",
            "project",
            "--db",
            str(tmp_path / "unavailable.db"),
            "--collection",
            "fixture",
            "--command",
            '["unused"]',
        ],
        input="",
        text=True,
        capture_output=True,
        timeout=10,
        env={**os.environ, "HOME": str(home), "MEMSEARCH_DIR": str(fixture.root / ".memsearch")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["type"] == "done"
    assert store.db.execute("SELECT count(*) FROM v2_sources").fetchone()[0] == 0


def test_recall_queries_serialize_with_capture_and_each_other(fixture, tmp_path, monkeypatch):
    from tests.opencode_v2_fixtures import SCRIPTS

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    command = tmp_path / "exclusive-query.py"
    command.write_text(
        "import os,time\nfrom pathlib import Path\n"
        "fd=os.open('query-active',os.O_CREAT|os.O_EXCL|os.O_WRONLY)\n"
        "try:\n"
        " Path('query-entries').open('a').write('entered\\n')\n"
        " time.sleep(.2)\n"
        "finally:\n os.close(fd)\n os.unlink('query-active')\n"
        "print('query completed')\n"
    )
    argv = [
        sys.executable,
        str(SCRIPTS / "capture.py"),
        "--project-dir",
        str(fixture.root),
        "--project-id",
        "reidentified",
        "--db",
        str(fixture.path),
        "--collection",
        "fixture",
        "--command",
        json.dumps([sys.executable, str(command)]),
        "--query",
        '["search","fixture"]',
        "--session-id",
        "session",
    ]
    with contextlib.ExitStack() as stack:
        with contextlib.closing(capture.CaptureStore(str(fixture.root))):
            processes = [
                stack.enter_context(subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                for _ in range(2)
            ]
            # Neither command may enter while a capture/index batch owns the lock.
            import time

            time.sleep(0.2)
            assert not (fixture.root / "query-entries").exists()
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
            assert stdout.strip() == "query completed"
    assert (fixture.root / "query-entries").read_text().count("entered") == 2
    fixture.conn.execute("UPDATE session_v2 SET workspace_id='foreign'")
    fixture.conn.commit()
    denied = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    assert denied.returncode == 1
    assert (fixture.root / "query-entries").read_text().count("entered") == 2


def test_two_roots_share_cli_lock_but_infer_concurrently(tmp_path, monkeypatch):
    import os
    import select

    from tests.opencode_v2_fixtures import SCRIPTS

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    command = tmp_path / "exclusive-cli.py"
    command.write_text(
        "import fcntl,os,sys,time\nfrom pathlib import Path\n"
        "home=Path.home()\n"
        "with (home/'database-lock').open('a') as lock:\n"
        " fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
        " with (home/'entries').open('a') as log: log.write(sys.argv[1]+'\\n')\n"
        " time.sleep(.15)\n"
        "print('completed')\n"
    )
    with contextlib.ExitStack() as stack:
        fixtures = [Fixture(tmp_path / name) for name in ("project-a", "project-b")]
        for item in fixtures:
            stack.callback(item.conn.close)
            with contextlib.closing(capture.CaptureStore(str(item.root))) as store:
                item.batch(store, initialize=True)
            item.turn()

        def start(item, *args):
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPTS / "capture.py"),
                    "--project-dir",
                    str(item.root),
                    "--project-id",
                    "p",
                    "--db",
                    str(item.path),
                    "--collection",
                    item.root.name,
                    "--command",
                    json.dumps([sys.executable, str(command)]),
                    *args,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "MEMSEARCH_DIR": str(item.root / ".memsearch")},
            )

            def cleanup():
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)

            stack.callback(cleanup)
            return process

        captures = [start(item) for item in fixtures]
        # Both helpers must reach native inference before either answer exists.
        # A global batch lock would prevent the second request from arriving.
        for process in captures:
            assert select.select([process.stdout], [], [], 10)[0]
            assert json.loads(process.stdout.readline())["type"] == "generate"
        assert not (home / "entries").exists()
        for process in captures:
            process.stdin.write('{"text":"- Concurrent inference fixture."}\n')
            process.stdin.flush()
        queries = [
            start(item, "--query", json.dumps([operation, "fixture"]), "--session-id", "session")
            for item, operation in zip(fixtures, ("search", "expand"), strict=True)
        ]
        for process in [*captures, *queries]:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stdout + stderr
        assert sorted((home / "entries").read_text().splitlines()) == ["expand", "index", "index", "search"]
        for item in fixtures:
            assert item.journals().count("<!-- session:") == 1


def test_cli_lock_cancellation_releases_waiter_owner_and_child(tmp_path, monkeypatch):
    import os
    import time

    from tests.opencode_v2_fixtures import SCRIPTS

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    command = tmp_path / "blocking-cli.py"
    command.write_text(
        "import fcntl,os,time\nfrom pathlib import Path\n"
        "home=Path.home()\n"
        "with (home/'database-lock').open('a') as lock:\n"
        " fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
        " (home/Path.cwd().name).write_text(str(os.getpid()))\n"
        " if Path.cwd().name=='project-a': time.sleep(60)\n"
        "print('completed')\n"
    )
    with contextlib.ExitStack() as stack:
        fixtures = [Fixture(tmp_path / name) for name in ("project-a", "project-b")]
        for item in fixtures:
            stack.callback(item.conn.close)

        def start(item):
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPTS / "capture.py"),
                    "--project-dir",
                    str(item.root),
                    "--project-id",
                    "p",
                    "--db",
                    str(item.path),
                    "--collection",
                    item.root.name,
                    "--command",
                    json.dumps([sys.executable, str(command)]),
                    "--query",
                    '["search","fixture"]',
                    "--session-id",
                    "session",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            def cleanup():
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)

            stack.callback(cleanup)
            return process

        owner = start(fixtures[0])
        deadline = time.monotonic() + 10
        while not (home / "project-a").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        child_pid = int((home / "project-a").read_text())
        waiter = start(fixtures[1])
        time.sleep(0.2)
        assert waiter.poll() is None
        assert not (home / "project-b").exists()
        waiter.terminate()
        waiter.communicate(timeout=5)
        assert waiter.returncode == 75
        # Cancellation releases the waiter's project lock as well as any CLI lock.
        successor = start(fixtures[1])
        owner.terminate()
        owner.communicate(timeout=5)
        assert owner.returncode == 75
        stdout, stderr = successor.communicate(timeout=10)
        assert successor.returncode == 0, stdout + stderr
        assert stdout.strip() == "completed"
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
