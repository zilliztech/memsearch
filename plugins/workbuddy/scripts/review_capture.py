#!/usr/bin/env python3
"""review_capture.py — 通用 agent hook 载荷抓取 + JSON Schema 推导（开发工具）。

独立于 handler.py，不参与 memsearch 管线：把 hooks.json（或任何 agent 框架的
hook 配置）手动指向本脚本，即可抓取真实事件 stdin 载荷并推导结构。

    python <path>/review_capture.py          # 由 hook 框架以 stdin 喂载荷

每次调用：
1. 从 stdin 读一个 hook 载荷 JSON（缺失/损坏/非对象均不抛错）；
2. 向 stdout 打印恰好一个 {"continue": true} 并 exit 0（绝不阻塞会话）；
3. 追加一条截断后的捕获记录到 <out>/captures/<event>.jsonl；
4. 重新推导并覆写 <out>/hook-schema.json —— 各事件节点的 JSON Schema：
   每个字段含数据类型 type（联合类型为数组）、出现次数 x-present、
   required（在该节点全部观测中出现）、x-examples（标量样例）。

产物目录：<project>/.hook-review/（HOOK_REVIEW_DIR 可覆盖）。
project 解析：payload.cwd → CODEBUDDY_PROJECT_DIR → CLAUDE_PROJECT_DIR → 进程 cwd。
仅标准库，无 memsearch 依赖，可拷到任意插件工程独立使用。
"""

import json
import os
import re
import sys
import time

MAX_STR = 500        # 捕获记录中单字符串最大长度
MAX_ITEMS = 50       # 捕获记录中单数组最大元素数
MAX_DEPTH = 8        # 捕获记录最大嵌套深度
MAX_EXAMPLES = 2     # schema 节点保留的标量样例数
EXAMPLE_STR = 80     # 样例字符串最大长度
STATS_NAME = "capture-stats.json"
SCHEMA_NAME = "hook-schema.json"


def _respond():
    try:
        sys.stdout.write('{"continue": true}')
        sys.stdout.flush()
    except Exception:
        pass


def _project_dir(payload):
    for cand in (
        payload.get("cwd"),
        os.environ.get("CODEBUDDY_PROJECT_DIR"),
        os.environ.get("CLAUDE_PROJECT_DIR"),
    ):
        if isinstance(cand, str) and cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.getcwd()


def _safe_name(event):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(event))[:60] or "unknown"


def _truncate(value, depth=0):
    """捕获记录净化：超长字符串/数组/深度截断，非 JSON 原生类型转字符串。"""
    if depth > MAX_DEPTH:
        return "…[MAX-DEPTH]"
    if isinstance(value, str):
        if len(value) > MAX_STR:
            return value[:MAX_STR] + "…[TRUNCATED %d chars total]" % len(value)
        return value
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        return {str(k)[:120]: _truncate(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_truncate(v, depth + 1) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append("…[TRUNCATED +%d more items]" % (len(value) - MAX_ITEMS))
        return items
    return str(value)[:MAX_STR]


# ---------------------------------------------------------------------------
# Schema 推导：stats 树 → JSON Schema
# ---------------------------------------------------------------------------

def _type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, dict):
        return "object"
    if isinstance(v, list):
        return "array"
    return "string"


def _new_node():
    # present=本节点被观测次数；props=object 子字段；items=array 元素合并节点
    return {"types": [], "present": 0, "examples": [], "props": {}, "items": None}


def _merge(node, value):
    t = _type_name(value)
    if t not in node["types"]:
        node["types"].append(t)
        node["types"].sort()
    node["present"] += 1
    if t in ("string", "boolean", "integer", "number", "null"):
        ex = value[:EXAMPLE_STR] if isinstance(value, str) else value
        ex_keys = [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in node["examples"]]
        if len(node["examples"]) < MAX_EXAMPLES and json.dumps(
            ex, ensure_ascii=False, sort_keys=True
        ) not in ex_keys:
            node["examples"].append(ex)
    if t == "object":
        for k, v in value.items():
            _merge(node["props"].setdefault(k, _new_node()), v)
    if t == "array":
        if node["items"] is None:
            node["items"] = _new_node()
        for item in value[:MAX_ITEMS]:
            _merge(node["items"], item)


def _node_schema(node):
    types = node["types"] or ["null"]
    out = {"type": types[0] if len(types) == 1 else types}
    out["x-present"] = node["present"]
    if node["examples"]:
        out["x-examples"] = node["examples"]
    if "object" in node["types"] and node["props"]:
        out["properties"] = {
            k: _node_schema(v) for k, v in sorted(node["props"].items())
        }
        out["required"] = sorted(
            k for k, v in node["props"].items() if v["present"] == node["present"]
        )
    if "array" in node["types"] and node["items"]:
        out["items"] = _node_schema(node["items"])
    return out


def _emit_schema(stats):
    events = {}
    for ev in sorted(stats["events"]):
        node = stats["events"][ev]
        body = _node_schema(node)
        body["x-observations"] = node["present"]
        events[ev] = body
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Agent hook stdin payloads — observed JSON Schema (auto-generated)",
        "x-generator": "review_capture.py (memsearch-workbuddy plugin dev tool)",
        "x-updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "x-note": "required=该字段在本节点全部观测中出现；x-present=出现次数；"
                  "type 为数组时表示观测到联合类型；由截断后的捕获推导（类型不受影响）",
        "events": events,
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    try:
        raw = sys.stdin.read() or ""
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {"_nonobject_payload": payload}
    except Exception:
        payload = {"_unparsed_stdin": raw[:MAX_STR]}

    event = payload.get("hook_event_name") or "unknown"
    out_dir = os.environ.get("HOOK_REVIEW_DIR") or os.path.join(
        _project_dir(payload), ".hook-review"
    )

    _respond()  # 先响应再落盘，不阻塞 hook 调用方

    try:
        captures_dir = os.path.join(out_dir, "captures")
        os.makedirs(captures_dir, exist_ok=True)

        capture = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "payload": _truncate(payload),
        }
        with open(
            os.path.join(captures_dir, _safe_name(event) + ".jsonl"),
            "a",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(capture, ensure_ascii=False) + "\n")

        stats_path = os.path.join(out_dir, STATS_NAME)
        try:
            with open(stats_path, encoding="utf-8") as f:
                stats = json.load(f)
            if not isinstance(stats.get("events"), dict):
                raise ValueError
        except Exception:
            stats = {"events": {}}

        node = stats["events"].setdefault(event, _new_node())
        _merge(node, capture["payload"])

        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=1)
        with open(os.path.join(out_dir, SCHEMA_NAME), "w", encoding="utf-8") as f:
            json.dump(_emit_schema(stats), f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
