#!/usr/bin/env python3
"""parse.py — WorkBuddy transcript JSONL → 扁平 turn 文本（L1 正则化核心，独立可测）。

依据 docs/memsearch-workbuddy-spec.md §0.2 / §3.3 实现：
- 只处理顶层 type=="message" 的行；role 取自顶层（不是嵌套 message.role）。
- content 为 OpenAI content-array：user→input_text / assistant→output_text，
  取各 block 的 text；兜底接受 "text" block 与纯字符串 content。
- 剥除 user 文本中嵌套的注入块：<system-reminder ...>、<user_context>、
  <additional_data>、<current_time>、<user_references>、<user_info>、
  <identity_context>（含配对块 / 自闭合 / 截断残留三种形态）。
- 只取末尾回合：最后一条真实 user 消息起，到文件尾。
- file-history-snapshot 行不硬丢弃（§3.3 保留策略）：能提取出有效正文
  （如 trackedFileBackups 的文件清单）才保留为 [System] 行，为空则自然跳过。
- reasoning / ai-title / function_call / function_call_result /
  resend-fork-notice 等行一律视为噪音跳过。

CLI:  python parse.py <transcript.jsonl>   → stdout 扁平文本（供 pipe）
API:  parse_last_turn(path) -> dict(text, last_user_id, line_count, kept, skipped_noise)
"""

import json
import os
import re
import sys

AGENT_LABEL = "WorkBuddy"

# 注入块标签黑名单（WorkBuddy 特有噪音，§0.2.3 / §3.3）
STRIP_TAGS = (
    "system-reminder",
    "user_context",
    "additional_data",
    "current_time",
    "user_references",
    "user_info",
    "identity_context",
)

# 配对块：<tag ...>...</tag>（DOTALL，非贪婪；同名块不嵌套，安全）
_RE_PAIRED = re.compile(
    r"<(%s)\b[^>]*>.*?<\s*/\s*\1\s*>" % "|".join(STRIP_TAGS),
    re.DOTALL,
)
# 截断残留：孤立的 <tag ...> 到文本末尾（transcript 写入截断时的兜底）
_RE_DANGLING = re.compile(
    r"<(?:%s)\b[^>]*>.*$" % "|".join(STRIP_TAGS),
    re.DOTALL,
)
# 自闭合或孤立标签：<tag .../> / <tag ...>（配对块已删后剩下的标签本身）
_RE_SELFCLOSE = re.compile(r"<(?:%s)\b[^>]*/?>" % "|".join(STRIP_TAGS))

# WorkBuddy 用 <user_query> 包裹真实用户话——属定界符而非噪音，只剥标签留正文
_RE_USER_QUERY = re.compile(r"</?user_query\s*>")

# snapshot 的 trackedFileBackups 清单可能极长（实测 100+ 路径），限长防爆 token
_SNAPSHOT_MAX_PATHS = 20


def strip_injected_blocks(text):
    """剥除 user 文本里的系统注入块，返回真实用户话（可能为空串）。"""
    if not text:
        return ""
    out = _RE_PAIRED.sub("", text)
    out = _RE_DANGLING.sub("", out)
    out = _RE_SELFCLOSE.sub("", out)
    out = _RE_USER_QUERY.sub("", out)
    return out.strip()


def extract_message_text(obj):
    """从 type=='message' 行提取 (role, text)；无法提取返回 (None, '')。"""
    if obj.get("type") != "message":
        return None, ""
    role = obj.get("role")
    if role not in ("user", "assistant"):
        return None, ""
    content = obj.get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            # user: input_text；assistant: output_text；兜底接受 text
            if block.get("type") in ("input_text", "output_text", "text"):
                t = block.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
    text = "\n".join(p.strip() for p in parts if p.strip())
    if role == "user":
        text = strip_injected_blocks(text)
    return role, text.strip()


def snapshot_text(obj):
    """file-history-snapshot 行的有效正文（§3.3 保留策略）；无正文返回 ''。"""
    snap = obj.get("snapshot")
    if isinstance(snap, dict):
        backups = snap.get("trackedFileBackups")
        if isinstance(backups, dict) and backups:
            paths = sorted(str(k) for k in backups)
            shown = paths[:_SNAPSHOT_MAX_PATHS]
            suffix = ""
            if len(paths) > _SNAPSHOT_MAX_PATHS:
                suffix = " ... (+%d more)" % (len(paths) - _SNAPSHOT_MAX_PATHS)
            return "tracked files: " + ", ".join(shown) + suffix
    content = obj.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return ""


def parse_last_turn(path, agent_label=AGENT_LABEL):
    """解析 transcript，只取末尾回合，返回扁平文本与元数据。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    meta = {
        "text": "",
        "last_user_id": "",
        "line_count": len(lines),
        "kept": 0,
        "skipped_noise": 0,
        "sentinel": "",
    }
    if not lines:
        meta["sentinel"] = "(empty transcript)"
        return meta

    # 反向扫：找最后一条剥噪后仍有正文的 user 消息
    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        role, text = extract_message_text(obj)
        if role == "user" and text:
            start_idx = i
            meta["last_user_id"] = obj.get("id", "") or ""
            break

    if start_idx is None:
        meta["sentinel"] = "(no user message found)"
        return meta

    out = [
        "=== Transcript of a conversation between User and %s ===" % agent_label
    ]
    seen_snapshots = set()  # 同一回合内完全重复的 snapshot 行只保留首次出现
    for raw in lines[start_idx:]:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            meta["skipped_noise"] += 1
            continue
        if obj.get("type") == "file-history-snapshot":
            snap = snapshot_text(obj)
            if snap:
                snap_line = "[System]: file-history-snapshot: %s" % snap
                if snap_line not in seen_snapshots:
                    seen_snapshots.add(snap_line)
                    out.append(snap_line)
                    meta["kept"] += 1
                else:
                    meta["skipped_noise"] += 1
            else:
                meta["skipped_noise"] += 1
            continue
        role, text = extract_message_text(obj)
        if role and text:
            label = "User" if role == "user" else "Assistant"
            out.append("[%s]: %s" % (label, text))
            meta["kept"] += 1
        elif obj.get("type") != "message":
            meta["skipped_noise"] += 1

    if len(out) == 1:  # 只有 header，没有任何有效正文
        meta["sentinel"] = "(empty turn)"
        return meta
    meta["text"] = "\n".join(out)
    return meta


def main(argv):
    path = argv[1] if len(argv) > 1 else ""
    if not path or not os.path.isfile(path):
        sys.stderr.write("ERROR: transcript not found: %s\n" % path)
        return 1
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    meta = parse_last_turn(path)
    print(meta["sentinel"] or meta["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
