"""maintenance 迁移（run_due_tasks + distill，platform 借 openclaw 槽）留档。

memsearch 包级 API 一律 mock，不触真实 LLM/后端。
"""

import dataclasses
import os
import types

import pytest

import handler


@dataclasses.dataclass
class _TC:
    provider: str = "native"


@dataclasses.dataclass
class _Ctx:
    task_config: _TC


def _fake_cfg(provider="siliconflow"):
    return types.SimpleNamespace(
        prompts=types.SimpleNamespace(
            project_review="", user_profile="", memory_to_skill=""
        ),
        plugins=types.SimpleNamespace(
            openclaw=types.SimpleNamespace(
                summarize=types.SimpleNamespace(provider=provider)
            )
        ),
    )


@pytest.fixture
def mock_pkg(monkeypatch, tmp_path):
    """mock memsearch 包级 API；返回调用记录。"""
    rec = {"due": None, "distill": None, "llm": []}
    cfg = _fake_cfg()
    monkeypatch.setattr("memsearch.config.resolve_config", lambda: cfg)

    def fake_due(**kw):
        rec["due"] = kw
        return []

    def fake_distill(**kw):
        rec["distill"] = kw
        return types.SimpleNamespace(__dict__={})

    def fake_llm(ctx, prompt, _cfg):
        rec["llm"].append(ctx.task_config.provider)
        return "{}"

    monkeypatch.setattr("memsearch.maintenance.run_due_tasks", fake_due)
    monkeypatch.setattr("memsearch.maintenance.run_task_llm", fake_llm)
    monkeypatch.setattr("memsearch.skills.distill", fake_distill)
    return rec, cfg


def test_platform_openclaw_and_paths(mock_pkg, tmp_path):
    rec, _ = mock_pkg
    mdir = str(tmp_path / ".memsearch")
    handler._maintenance(str(tmp_path), mdir)
    assert rec["due"]["platform"] == "openclaw"  # 白名单无 workbuddy，借槽
    assert rec["due"]["project_dir"] == str(tmp_path)
    assert rec["due"]["memsearch_dir"] == mdir
    assert rec["distill"]["platform"] == "openclaw"


def test_native_provider_falls_back_to_summarize(mock_pkg, tmp_path):
    rec, _ = mock_pkg
    handler._maintenance(str(tmp_path), str(tmp_path / ".memsearch"))
    runner = rec["due"]["llm_runner"]
    runner(_Ctx(_TC("native")), "p")
    assert rec["llm"] == ["siliconflow"]  # native → summarize provider 回落


def test_explicit_provider_passthrough(mock_pkg, tmp_path):
    rec, _ = mock_pkg
    handler._maintenance(str(tmp_path), str(tmp_path / ".memsearch"))
    rec["due"]["llm_runner"](_Ctx(_TC("other-prov")), "p")
    assert rec["llm"] == ["other-prov"]


def test_prompt_defaults_point_to_shared(mock_pkg, tmp_path):
    _, cfg = mock_pkg
    handler._maintenance(str(tmp_path), str(tmp_path / ".memsearch"))
    for task in ("project_review", "user_profile", "memory_to_skill"):
        p = getattr(cfg.prompts, task)
        assert p.endswith(os.path.join("_shared", "prompts", task + ".txt"))
        assert os.path.isfile(p)  # 仓内 _shared/prompts 真实存在


def test_pidfile_cleaned_and_errors_swallowed(mock_pkg, monkeypatch, tmp_path):
    rec, _ = mock_pkg
    mdir = tmp_path / ".memsearch"
    mdir.mkdir()
    pidfile = mdir / handler.MAINT_PID_NAME
    pidfile.write_text("123", encoding="utf-8")

    def boom(**kw):
        raise RuntimeError("task exploded")

    monkeypatch.setattr("memsearch.maintenance.run_due_tasks", boom)
    assert handler._maintenance(str(tmp_path), str(mdir)) == 0
    assert rec["distill"] is not None  # due 炸了不影响 distill
    assert not pidfile.exists()


def test_bg_run_skip_if_running(monkeypatch, tmp_path):
    mdir = str(tmp_path)
    with open(os.path.join(mdir, handler.MAINT_PID_NAME), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))  # 本进程必然存活
    spawned = []

    class FakePopen:
        def __init__(self, *a, **k):
            spawned.append(a)
            self.pid = 1

    monkeypatch.setattr(handler.subprocess, "Popen", FakePopen)
    handler._bg_run(handler.MAINT_PID_NAME, ["x"], mdir)
    assert not spawned  # 存活中不重复点火
