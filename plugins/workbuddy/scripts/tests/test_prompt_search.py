"""UserPromptSubmit 搜索注入的 pytest 留档。

后端交互一律 mock；opt-in E2E（MEMSEARCH_SEARCH_E2E=1）用只读集合
cherry_memory 验证真实 memsearch search -j 往返。
"""

import json
import os

import pytest

import handler

ROWS = [
    {
        "content": "line1\r\nline2   spaced",
        "heading": "Session 22:45",
        "source": "D:\\proj\\.memsearch\\memory\\2026-08-26.md",
        "score": 0.42,
    },
    {
        "content": "second hit",
        "heading": "",
        "source": "D:\\proj\\.memsearch\\memory\\2026-08-25.md",
        "score": 0.41,
    },
]


def _ctx(tmp_path):
    return {
        "project_dir": str(tmp_path),
        "memsearch_dir": os.path.join(str(tmp_path), ".memsearch"),
        "parse_mod": None,
    }


@pytest.fixture
def mock_run(monkeypatch):
    """替换 CLI 层；返回可编程的 (rc, stdout) 与调用记录。"""
    calls = []
    state = {"rc": 0, "out": json.dumps(ROWS)}

    def fake(args, input_text=None, timeout=60, env=None):
        calls.append(args)
        return state["rc"], state["out"]

    monkeypatch.setattr(handler, "_find_memsearch", lambda: "C:/fake/memsearch.exe")
    monkeypatch.setattr(handler, "_run", fake)
    return calls, state


def test_injects_top2_as_context(mock_run, tmp_path):
    calls, _ = mock_run
    out = handler.on_user_prompt_submit(
        {"prompt": "how does watch work?"}, _ctx(tmp_path)
    )
    assert out["systemMessage"] == "[memsearch] 2 related memories"
    ctx_text = out["hookSpecificOutput"]["additionalContext"]
    assert "line1 line2 spaced" in ctx_text  # 空白折叠
    assert "second hit" in ctx_text
    assert "2026-08-26.md › Session 22:45" in ctx_text  # basename › heading
    assert "2026-08-25.md" in ctx_text  # 无 heading 只有 basename
    args = calls[0]
    assert args[1:2] == ["search"]
    assert args[2] == "how does watch work?"
    assert "-c" in args and handler._derive_collection(str(tmp_path)) in args
    assert args[args.index("-k") + 1] == "2"
    assert "-j" in args


def test_query_truncated_to_500(mock_run, tmp_path):
    calls, _ = mock_run
    handler.on_user_prompt_submit({"prompt": "x" * 900}, _ctx(tmp_path))
    assert len(calls[0][2]) == 500


@pytest.mark.parametrize(
    "rc,out_text",
    [(1, "[]"), (0, "not-json"), (0, "[]"), (-124, ""), (0, '{"x":1}')],
)
def test_failures_fall_back_to_marker(mock_run, tmp_path, rc, out_text):
    _, state = mock_run
    state["rc"], state["out"] = rc, out_text
    out = handler.on_user_prompt_submit({"prompt": "a long enough prompt"}, _ctx(tmp_path))
    assert out == {"continue": True, "systemMessage": "[memsearch] Memory available"}


def test_cli_missing_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(handler, "_find_memsearch", lambda: "")
    out = handler.on_user_prompt_submit({"prompt": "a long enough prompt"}, _ctx(tmp_path))
    assert out == {"continue": True, "systemMessage": "[memsearch] Memory available"}


def test_short_prompt_skips_search(mock_run, tmp_path):
    calls, _ = mock_run
    out = handler.on_user_prompt_submit({"prompt": "短"}, _ctx(tmp_path))
    assert out == {"continue": True}
    assert not calls


def test_content_capped_at_400(mock_run, tmp_path):
    _, state = mock_run
    state["out"] = json.dumps([{"content": "y" * 800, "heading": "", "source": "a.md"}])
    out = handler.on_user_prompt_submit({"prompt": "a long enough prompt"}, _ctx(tmp_path))
    assert "y" * 400 in out["hookSpecificOutput"]["additionalContext"]
    assert "y" * 401 not in out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.skipif(
    os.environ.get("MEMSEARCH_SEARCH_E2E") != "1",
    reason="opt-in: 命中真实后端（MEMSEARCH_SEARCH_E2E=1 启用）",
)
def test_real_search_roundtrip(tmp_path):
    """只读探测：cherry_memory 为既有填充集合，top-2 应非空。"""
    hits = handler._search_memories("memory", "cherry_memory", str(tmp_path))
    assert len(hits) == 2
    assert all(h[0] for h in hits)
