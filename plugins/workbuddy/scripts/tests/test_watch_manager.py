"""watch 进程管理 + SessionStart 接线的 pytest 留档。

进程管理用无害 sleeper 子进程替身；E2E（真实 memsearch watch + 远端集合）
默认跳过，MEMSEARCH_WATCH_E2E=1 时启用并自清理远端测试集合。
"""

import hashlib
import os
import sys
import time

import pytest

import handler

SLEEPER = [sys.executable, "-c", "import time; time.sleep(300)"]


@pytest.fixture
def mdir(tmp_path):
    return str(tmp_path / ".memsearch")


def _pidfile(mdir):
    return os.path.join(mdir, handler.WATCH_PID_NAME)


# ---------------------------------------------------------------------------
# 进程管理（sleeper 替身，无外部依赖）
# ---------------------------------------------------------------------------

def test_start_writes_pid_and_log(mdir):
    pid = handler._watch_start(SLEEPER, mdir)
    try:
        assert pid > 0
        assert open(_pidfile(mdir), encoding="utf-8").read().strip() == str(pid)
        assert handler._watch_pid(mdir) == pid
        assert os.path.isfile(os.path.join(mdir, handler.WATCH_LOG_NAME))
    finally:
        handler._watch_stop(mdir)
    assert handler._watch_pid(mdir) == 0


def test_start_idempotent(mdir):
    p1 = handler._watch_start(SLEEPER, mdir)
    p2 = handler._watch_start(SLEEPER, mdir)
    try:
        assert p1 == p2 > 0
    finally:
        handler._watch_stop(mdir)


def test_stale_pid_cleaned(mdir):
    os.makedirs(mdir)
    with open(_pidfile(mdir), "w", encoding="utf-8") as f:
        f.write("99999999")
    assert handler._watch_pid(mdir) == 0
    assert not os.path.exists(_pidfile(mdir))


def test_stop_terminates_and_cleans(mdir):
    pid = handler._watch_start(SLEEPER, mdir)
    assert pid > 0
    assert handler._watch_stop(mdir) is True
    assert handler._watch_pid(mdir) == 0  # pidfile 已清


def test_stop_when_not_running(mdir):
    assert handler._watch_stop(mdir) is False


def test_log_rotation_keeps_one_old(mdir):
    os.makedirs(mdir)
    log = os.path.join(mdir, handler.WATCH_LOG_NAME)
    with open(log, "w", encoding="utf-8") as f:
        f.write("old")
    pid = handler._watch_start(SLEEPER, mdir)
    try:
        with open(log + ".1", encoding="utf-8") as f:
            assert f.read() == "old"
    finally:
        handler._watch_stop(mdir)


def test_server_milvus_detection(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[milvus]\nuri = "https://x.zillizcloud.com"\n', encoding="utf-8")
    assert handler._server_milvus(str(cfg)) is True
    cfg.write_text('[milvus]\nuri = "./lite.db"\n', encoding="utf-8")
    assert handler._server_milvus(str(cfg)) is False
    cfg.write_text("[other]\n", encoding="utf-8")
    assert handler._server_milvus(str(cfg)) is False


# ---------------------------------------------------------------------------
# SessionStart 接线（monkeypatch 隔离真实 CLI / 进程）
# ---------------------------------------------------------------------------

def _ctx(project_dir):
    return {
        "project_dir": str(project_dir),
        "memsearch_dir": os.path.join(str(project_dir), ".memsearch"),
        "parse_mod": None,
    }


def _wire_mocks(monkeypatch, server):
    monkeypatch.setattr(handler, "_find_memsearch", lambda: "C:/fake/memsearch.exe")
    monkeypatch.setattr(handler, "_server_milvus", lambda *a, **k: server)
    calls = {"start": [], "bg": []}
    monkeypatch.setattr(
        handler, "_watch_start", lambda cmd, d: calls["start"].append(cmd) or 4242
    )
    monkeypatch.setattr(
        handler, "_bg_index", lambda *a: calls["bg"].append(a) or None
    )
    return calls


def _status_line(out):
    return out.get("systemMessage", "")  # 无 preview 时状态行在 systemMessage


def test_sessionstart_watch_server_replaces_bg_index(monkeypatch, tmp_path):
    memory = tmp_path / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    calls = _wire_mocks(monkeypatch, server=True)
    monkeypatch.setenv("MEMSEARCH_WB_WATCH", "1")
    out = handler.on_session_start({"cwd": str(tmp_path)}, _ctx(tmp_path))
    assert "watch: running pid 4242" in _status_line(out)
    assert calls["start"] and calls["start"][0][1:3] == ["watch", str(memory)]
    assert "-c" in calls["start"][0]
    assert not calls["bg"]  # watch 取代一次性索引


def test_sessionstart_watch_lite_falls_back(monkeypatch, tmp_path):
    memory = tmp_path / ".memsearch" / "memory"
    memory.mkdir(parents=True)
    calls = _wire_mocks(monkeypatch, server=False)
    monkeypatch.setenv("MEMSEARCH_WB_WATCH", "1")
    out = handler.on_session_start({"cwd": str(tmp_path)}, _ctx(tmp_path))
    assert "watch: skipped(Lite)" in _status_line(out)
    assert not calls["start"]
    assert calls["bg"]  # Lite 退回一次性索引


def test_sessionstart_default_no_watch(monkeypatch, tmp_path):
    (tmp_path / ".memsearch" / "memory").mkdir(parents=True)
    calls = _wire_mocks(monkeypatch, server=True)
    monkeypatch.delenv("MEMSEARCH_WB_WATCH", raising=False)
    out = handler.on_session_start({"cwd": str(tmp_path)}, _ctx(tmp_path))
    assert "watch:" not in _status_line(out)
    assert not calls["start"]
    assert calls["bg"]


# ---------------------------------------------------------------------------
# E2E：真实 memsearch watch，验证外部文件变更被重索引（opt-in）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("MEMSEARCH_WATCH_E2E") != "1",
    reason="opt-in: 命中真实后端（MEMSEARCH_WATCH_E2E=1 启用）",
)
def test_watch_reindexes_external_edit(tmp_path):
    ms = handler._find_memsearch()
    if not ms or not handler._server_milvus():
        pytest.skip("memsearch CLI 或 server milvus 不可用")
    mdir = str(tmp_path / ".memsearch")
    memory = os.path.join(mdir, "memory")
    os.makedirs(memory)
    md = os.path.join(memory, "2026-01-01.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# seed\n\n- seed bullet\n")
    coll = "wb_watch_e2e_" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:8]
    pid = handler._watch_start([ms, "watch", memory, "-c", coll], mdir)
    assert pid > 0
    try:
        time.sleep(5)  # 启动未即崩
        assert handler._watch_pid(mdir) == pid
        with open(md, "a", encoding="utf-8") as f:
            f.write("\n- external edit %d\n" % time.time())
        deadline = time.time() + 60
        indexed = False
        while time.time() < deadline:  # 任一证据：index-state 出现/更新
            for root, _dirs, files in os.walk(mdir):
                if ".index-state.json" in files:
                    indexed = True
            if indexed:
                break
            time.sleep(2)
        assert indexed, "60s 内未见 .index-state.json（外部变更未被重索引）"
    finally:
        handler._watch_stop(mdir)
        _drop_collection(coll)


def _drop_collection(name):
    """best-effort 清理远端测试集合（凭据取自全局 config）。"""
    try:
        import tomllib

        cfg = os.path.join(os.path.expanduser("~"), ".memsearch", "config.toml")
        with open(cfg, "rb") as f:
            m = tomllib.load(f).get("milvus", {})
        from pymilvus import MilvusClient

        c = MilvusClient(uri=m.get("uri"), token=m.get("token") or None)
        if c.has_collection(name):
            c.drop_collection(name)
    except Exception:
        pass
