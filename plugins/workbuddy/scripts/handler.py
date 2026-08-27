#!/usr/bin/env python3
"""handler.py — memsearch × WorkBuddy 对接层主逻辑（事件分派 + 真实后端调用）。

依据 docs/memsearch-workbuddy-spec.md §3.2 实现，接通真实 memsearch CLI 后端。

事件分派：
- SessionStart      → 状态行 + 最近记忆预览注入 additionalContext + skills hint
                      + 后台一次性 index（skip-if-running）+ 远端索引滞后等待提示
                      + 可选常驻 watch（MEMSEARCH_WB_WATCH=1，仅 server 模式）
- UserPromptSubmit  → "[memsearch] Memory available" 记号
- Stop/SubagentStop → parse.py 解析 → memsearch summarize（stdin，110s 超时）
                      → 追加当日 memory/*.md（懒写 ## Session 标题 + 锚点）
                      → memsearch index → 写 .last-index-completed 隐含时间戳
- PreCompact/其他   → 静默放行

隐含时间戳机制（spec §7-12）：Stop 索引完成后写 .memsearch/.last-index-completed
（epoch 秒）；SessionStart 读它，处于 MEMSEARCH_WB_LAG_WINDOW（默认 1200s）内则在
systemMessage 追加「远端索引统计追平中，新记忆可能暂时查无结果」提示。
只读一个小文件，不发 RPC、不阻塞。

输出契约：任何路径都向 stdout 打印恰好一个合法 JSON 并 exit 0（C2 不阻塞会话）。
不依赖 CODEBUDDY_PLUGIN_ROOT（C3，路径一律用 __file__ 推导）。
MEMSEARCH_DISABLE=1 时直接空响应（C4 防重入）。
遵循 spec §3.6.3 防垃圾红线：除 memory/*.md 追加与自管理的
.last-index-completed/.index.pid 外，不落任何中间/审阅文件。
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# spec §7-12：Zilliz serverless row_count 统计滞后实测 ~15 分钟，窗口默认 1200s
LAG_WINDOW_S = int(os.environ.get("MEMSEARCH_WB_LAG_WINDOW", "1200") or 1200)
INDEX_TS_NAME = ".last-index-completed"
INDEX_PID_NAME = ".index.pid"
MAINT_PID_NAME = ".maintenance.pid"
WATCH_PID_NAME = ".watch.pid"
WATCH_LOG_NAME = "watch.log"
OPENCLAW_AGENT_NAME = "WorkBuddy"


def _load_parse():
    spec = importlib.util.spec_from_file_location(
        "wb_parse", os.path.join(SCRIPT_DIR, "parse.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _respond(obj):
    """向 stdout 打印恰好一个 JSON 对象并 flush。"""
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False))
        sys.stdout.flush()
    except Exception:
        try:
            sys.stdout.write('{"continue":true}')
            sys.stdout.flush()
        except Exception:
            pass


def _project_dir(payload):
    """工程根解析：stdin cwd 优先，其次宿主 env，最后进程 cwd（C3 不依赖 PLUGIN_ROOT）。"""
    for cand in (
        payload.get("cwd"),
        os.environ.get("CODEBUDDY_PROJECT_DIR"),
        os.environ.get("CLAUDE_PROJECT_DIR"),
    ):
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.getcwd()


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# 后端调用助手
# ---------------------------------------------------------------------------

def _find_memsearch():
    return shutil.which("memsearch") or ""


def _derive_collection(project_dir):
    """复刻 derive-collection.sh：ms_<sanitized_basename>_<sha256前8位>。

    实测钉死：哈希输入必须是 MSYS Unix 形态绝对路径（D:\\a\\b → /d/a/b，
    盘符小写、无尾斜杠），否则与既有 collection 分裂。
    """
    p = os.path.abspath(project_dir).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        p = "/%s/%s" % (m.group(1).lower(), m.group(2))
    base = os.path.basename(p.rstrip("/"))
    sanitized = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", base.lower())).strip("_")[:40]
    digest = hashlib.sha256(p.encode("utf-8")).hexdigest()[:8]
    return "ms_%s_%s" % (sanitized, digest)


def _child_env(memsearch_dir):
    env = os.environ.copy()
    env["MEMSEARCH_NO_WATCH"] = "1"
    env["MEMSEARCH_DIR"] = memsearch_dir
    return env


def _run(args, input_text=None, timeout=60, env=None):
    """跑后端子进程，返回 (rc, stdout)；异常/超时返回 (负码, '')。绝不抛出。

    Windows 下 pythonw（无控制台）父进程拉起的控制台子系统 exe 会新建黑色
    控制台窗口，故必须带 CREATE_NO_WINDOW 抑制。
    """
    try:
        r = subprocess.run(
            args,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.returncode, r.stdout or ""
    except subprocess.TimeoutExpired:
        return -124, ""
    except Exception:
        return -1, ""


def _write_index_ts(memsearch_dir):
    """隐含时间戳：索引完成后写 epoch 秒（单行文本，~0ms）。"""
    try:
        _write_text(
            os.path.join(memsearch_dir, INDEX_TS_NAME), str(int(time.time()))
        )
    except Exception:
        pass


def _lag_hint(memsearch_dir):
    """读隐含时间戳；处于滞后窗口内则返回等待提示，否则空串。纯文件读，零 RPC。"""
    try:
        with open(
            os.path.join(memsearch_dir, INDEX_TS_NAME), encoding="utf-8"
        ) as f:
            ts = int(f.read().strip())
    except Exception:
        return ""
    age = int(time.time()) - ts
    if 0 <= age < LAG_WINDOW_S:
        return (
            "远端索引统计追平中（上次索引完成于 %d 分钟前），新记忆可能暂时"
            "查无结果——Zilliz serverless 最终一致性延迟，通常 ≤%d 分钟自愈"
            % (max(1, age // 60), LAG_WINDOW_S // 60)
        )
    return ""


def _bg_run(pid_name, argv, memsearch_dir):
    """detached 子进程通用点火：pidfile 存活探针 skip-if-running（防抖）。"""
    pidfile = os.path.join(memsearch_dir, pid_name)
    try:
        if os.path.isfile(pidfile):
            with open(pidfile, encoding="utf-8") as f:
                old_pid = int(f.read().strip() or "0")
            if old_pid > 0:
                os.kill(old_pid, 0)  # 存活探测，进程不在则抛 OSError
                return  # 上一个还在跑，跳过
    except (OSError, ValueError):
        pass  # 进程已死或 pidfile 损坏，继续起新进程
    except Exception:
        pass
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        p = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
        _write_text(pidfile, str(p.pid))
    except Exception:
        pass


def _bg_index(handler_path, memory_dir, collection, memsearch_dir):
    """SessionStart 后台一次性索引：detached 子进程跑 --index-and-stamp。"""
    _bg_run(
        INDEX_PID_NAME,
        [
            sys.executable,
            handler_path,
            "--index-and-stamp",
            memory_dir,
            collection,
            memsearch_dir,
        ],
        memsearch_dir,
    )


def _index_and_stamp(memory_dir, collection, memsearch_dir):
    """隐藏子命令入口：同步 index 后写时间戳（供 _bg_index 以独立进程执行）。"""
    ms = _find_memsearch()
    if not ms:
        return 1
    args = [ms, "index", memory_dir]
    if collection:
        args += ["-c", collection]
    _run(args, timeout=300, env=_child_env(memsearch_dir))
    _write_index_ts(memsearch_dir)
    try:
        os.remove(os.path.join(memsearch_dir, INDEX_PID_NAME))
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# maintenance：到期任务（project_review/user_profile）+ memory_to_skill 蒸馏。
# config.py 的 platform 白名单无 workbuddy → 借 openclaw 槽（与 summarize 同约定）；
# provider=native 时回落到 openclaw summarize provider（WorkBuddy 无 headless CLI）。
# ---------------------------------------------------------------------------

def _maintenance(project_dir, memsearch_dir):
    """隐藏子命令：跑 due 的 maintenance 任务 + 技能蒸馏，清 pidfile。"""
    try:
        import dataclasses

        from memsearch.config import resolve_config
        from memsearch.maintenance import run_due_tasks, run_task_llm
        from memsearch.skills import distill
    except Exception:
        return 1
    cfg = resolve_config()
    # prompt 缺省指向 _shared/prompts（与上游 plugins/_shared 同构）
    shared = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "_shared", "prompts"))
    for task in ("project_review", "user_profile", "memory_to_skill"):
        if not getattr(cfg.prompts, task, ""):
            f = os.path.join(shared, task + ".txt")
            if os.path.isfile(f):
                setattr(cfg.prompts, task, f)
    try:
        fallback = cfg.plugins.openclaw.summarize.provider or ""
    except Exception:
        fallback = ""

    def llm_runner(ctx, prompt):
        if (ctx.task_config.provider or "native").strip() in ("", "native") and fallback:
            ctx = dataclasses.replace(
                ctx, task_config=dataclasses.replace(ctx.task_config, provider=fallback)
            )
        return run_task_llm(ctx, prompt, cfg)

    try:
        run_due_tasks(
            platform="openclaw",
            project_dir=project_dir,
            memsearch_dir=memsearch_dir,
            cfg=cfg,
            llm_runner=llm_runner,
        )
    except Exception:
        pass
    try:
        distill(
            platform="openclaw",
            project_dir=project_dir,
            memsearch_dir=memsearch_dir,
            cfg=cfg,
            llm_runner=llm_runner,
        )
    except Exception:
        pass
    try:
        os.remove(os.path.join(memsearch_dir, MAINT_PID_NAME))
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# watch 常驻进程管理（吸收自 watch-manager.sh；仅 server 模式使用，Lite 跳过）
# ---------------------------------------------------------------------------

def _watch_pid(memsearch_dir):
    """探测 watch 存活并清理 stale pidfile。返回 pid，未运行返回 0。"""
    pidfile = os.path.join(memsearch_dir, WATCH_PID_NAME)
    try:
        with open(pidfile, encoding="utf-8") as f:
            pid = int(f.read().strip() or "0")
    except Exception:
        return 0
    if pid > 0:
        try:
            os.kill(pid, 0)  # 存活探测
            return pid
        except OSError:
            pass
    try:
        os.remove(pidfile)
    except Exception:
        pass
    return 0


def _server_milvus(cfg_path=None):
    """全局 config 的 milvus.uri 为 http(s) 即 server 模式；Lite 文件锁下 watch 有害（上游 common.sh 规则）。"""
    if cfg_path is None:
        cfg_path = os.path.join(os.path.expanduser("~"), ".memsearch", "config.toml")
    try:
        import tomllib

        with open(cfg_path, "rb") as f:
            uri = str(tomllib.load(f).get("milvus", {}).get("uri", ""))
        return uri.startswith("http")
    except Exception:
        return False


def _watch_start(cmd, memsearch_dir):
    """启动 watch（detached，stderr→watch.log，轮转保留 .1）。已在跑返回现有 pid。"""
    pid = _watch_pid(memsearch_dir)
    if pid:
        return pid
    try:
        os.makedirs(memsearch_dir, exist_ok=True)
        log = os.path.join(memsearch_dir, WATCH_LOG_NAME)
        if os.path.isfile(log):
            os.replace(log, log + ".1")  # 只留最近一个旧日志
        env = os.environ.copy()
        env["MEMSEARCH_DIR"] = memsearch_dir
        env.pop("MEMSEARCH_NO_WATCH", None)  # 显式 watch 不应带 NO_WATCH
        err = open(log, "ab")
        try:
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0),
                start_new_session=os.name != "nt",
                close_fds=True,
                env=env,
            )
        finally:
            err.close()
        _write_text(os.path.join(memsearch_dir, WATCH_PID_NAME), str(p.pid))
        return p.pid
    except Exception:
        return 0


def _watch_stop(memsearch_dir, grace_s=3):
    """停止 watch：POSIX INT→KILL；Windows 无头进程无控制台可分派 INT，直接 TERM（TerminateProcess）。返回是否曾存活。"""
    pid = _watch_pid(memsearch_dir)
    if not pid:
        return False
    sigs = (
        [signal.SIGTERM]
        if os.name == "nt"
        else [signal.SIGINT, getattr(signal, "SIGKILL", signal.SIGTERM)]
    )
    for sig in sigs:
        try:
            os.kill(pid, sig)
        except Exception:
            pass
        for _ in range(grace_s):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            continue
        break
    try:
        os.remove(os.path.join(memsearch_dir, WATCH_PID_NAME))
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# SessionStart：状态行 + 最近记忆预览（纯文件读，零后端调用）
# ---------------------------------------------------------------------------

def _resolve_summarize_provider():
    """按 §3.4 规则从全局 ~/.memsearch/config.toml 解析 summarize 将用的 provider。

    只读配置文件（不调用 memsearch config CLI）。返回 dict 供状态行与失败诊断。
    安全约束：绝不回显 api_key / token 字段值。
    """
    result = {
        "config_path": "",
        "provider": "",
        "model": "",
        "openclaw_summarize": {},
        "error": "",
    }
    cfg_path = os.path.expanduser(os.path.join("~", ".memsearch", "config.toml"))
    result["config_path"] = cfg_path
    if not os.path.isfile(cfg_path):
        result["error"] = (
            "global config not found: %s — 请先创建 ~/.memsearch/config.toml "
            "并配置 [llm.providers.<name>]" % cfg_path
        )
        return result
    try:
        import tomllib

        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)
    except ImportError:
        result["error"] = "tomllib unavailable (python<3.11) — provider 解析跳过"
        return result
    except Exception as e:
        result["error"] = "config.toml 解析失败: %s" % e
        return result

    providers = cfg.get("llm", {}).get("providers", {})
    if isinstance(providers, dict):
        for name, p in providers.items():
            if isinstance(p, dict) and p.get("type") and p.get("model"):
                result["provider"] = name
                result["model"] = str(p.get("model"))
                break
    oc_sum = cfg.get("plugins", {}).get("openclaw", {}).get("summarize", {})
    if isinstance(oc_sum, dict):
        # 只回显非敏感键
        result["openclaw_summarize"] = {
            k: v for k, v in oc_sum.items() if k not in ("api_key", "token")
        }
    if not result["provider"]:
        result["error"] = (
            "~/.memsearch/config.toml 中无可用 [llm.providers.<name>]"
            "（需 type 与 model 均非空）— summarize 将无 provider 可用，"
            "按 §3.4 不静默降级"
        )
    return result


def _recent_memory_preview(memory_dir, max_files=2, max_lines=40):
    """最近 daily 记忆预览：只保留 ##/###/#### 标题与 '- ' bullet 行（对齐 claude 版 awk 逻辑）。"""
    if not os.path.isdir(memory_dir):
        return ""
    daily = [
        f
        for f in os.listdir(memory_dir)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", f)
    ]
    if not daily:
        return ""
    daily.sort(reverse=True)
    sections = []
    for fname in daily[:max_files]:
        kept = []
        try:
            with open(
                os.path.join(memory_dir, fname), encoding="utf-8", errors="replace"
            ) as f:
                for line in f:
                    s = line.rstrip("\n")
                    if re.match(r"^#{2,4}\s", s) or s.startswith("- "):
                        kept.append(s)
        except Exception:
            continue
        kept = kept[-max_lines:]
        if any(l.startswith("- ") for l in kept):
            sections.append("## %s\n%s" % (fname, "\n".join(kept)))
    if not sections:
        return ""
    return "# Recent Memory\n\n" + "\n\n".join(sections)


def on_session_start(payload, ctx):
    proj = ctx["project_dir"]
    memsearch_dir = ctx["memsearch_dir"]
    memory_dir = os.path.join(memsearch_dir, "memory")
    collection = _derive_collection(proj)

    prov = _resolve_summarize_provider()
    if prov["provider"]:
        prov_desc = "%s/%s" % (prov["provider"], prov["model"])
    else:
        prov_desc = "NOT CONFIGURED — %s" % prov["error"]

    status = (
        "[memsearch-wb] summarize route:"
        " plugins.openclaw.summarize.* --agent-name WorkBuddy | provider: %s"
        % prov_desc
    )

    ms = _find_memsearch()
    if ms:
        # skills hint（对齐 claude 插件契约：无候选时 exit=1 静默，空输出即无 hint）
        if os.path.isdir(os.path.join(memsearch_dir, "skill-candidates")):
            rc, hint = _run(
                [ms, "skills", "status", "--hint"],
                timeout=5,
                env=_child_env(memsearch_dir),
            )
            if rc == 0 and hint.strip():
                status += " | " + hint.strip()
        # watch 管理：MEMSEARCH_WB_WATCH=1 且 server 模式时起常驻 watch（替代一次性索引）
        watch_on = os.environ.get("MEMSEARCH_WB_WATCH", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        wpid = _watch_pid(memsearch_dir)
        if watch_on and _server_milvus():
            if not wpid and os.path.isdir(memory_dir):
                wpid = _watch_start([ms, "watch", memory_dir, "-c", collection], memsearch_dir)
            status += " | watch: %s" % ("running pid %d" % wpid if wpid else "start failed")
        else:
            if watch_on:
                status += " | watch: skipped(Lite)"  # Lite 文件锁与 watch 冲突，退回一次性索引
            elif wpid:
                status += " | watch: running pid %d (unmanaged)" % wpid
            # 后台一次性索引（detached，skip-if-running），完成后由子进程写时间戳
            if os.path.isdir(memory_dir):
                _bg_index(
                    os.path.join(SCRIPT_DIR, "handler.py"),
                    memory_dir,
                    collection,
                    memsearch_dir,
                )
    else:
        status += " | ERROR: memsearch CLI not found on PATH"
    # §7-12 滞后窗口等待提示（纯文件读，零 RPC）
    lag = _lag_hint(memsearch_dir)
    if lag:
        status += " | " + lag

    context = _recent_memory_preview(memory_dir)

    response = {"continue": True, "systemMessage": status}
    if context:
        response["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    return response


# ---------------------------------------------------------------------------
# UserPromptSubmit：后端搜索 top-2 记忆注入；任何失败退回轻量记号，绝不阻塞
# ---------------------------------------------------------------------------

PROMPT_MIN_LEN = 10
SEARCH_TOP_K = 2
SEARCH_TIMEOUT_S = 6  # hook 预算 10s，给 WorkBuddy 侧留余量
SEARCH_QUERY_MAX = 500  # 查询截断，约束 embedding 成本
MEM_CTX_MAX = 400  # 单条注入正文上限


def _search_memories(query, collection, memsearch_dir, timeout=SEARCH_TIMEOUT_S):
    """memsearch search -j → [(text, heading, source)]；任何失败返回 []。"""
    ms = _find_memsearch()
    if not ms:
        return []
    rc, out = _run(
        [ms, "search", query[:SEARCH_QUERY_MAX], "-c", collection,
         "-k", str(SEARCH_TOP_K), "-j"],
        timeout=timeout,
        env=_child_env(memsearch_dir),
    )
    if rc != 0 or not out.strip():
        return []
    try:
        rows = json.loads(out)
    except ValueError:
        return []
    hits = []
    for r in rows if isinstance(rows, list) else []:
        text = re.sub(r"\s+", " ", str(r.get("content", ""))).strip()
        if text:
            hits.append(
                (
                    text[:MEM_CTX_MAX],
                    str(r.get("heading") or ""),
                    os.path.basename(str(r.get("source") or "")),
                )
            )
    return hits


def on_user_prompt_submit(payload, ctx):
    prompt = (payload.get("prompt") or "").strip()
    if len(prompt) < PROMPT_MIN_LEN:
        return {"continue": True}
    resp = {"continue": True, "systemMessage": "[memsearch] Memory available"}
    hits = _search_memories(
        prompt, _derive_collection(ctx["project_dir"]), ctx["memsearch_dir"]
    )
    if not hits:
        return resp
    lines = ["[memsearch] 相关历史记忆（按相关度排序，仅供参考）:"]
    for i, (text, heading, source) in enumerate(hits, 1):
        where = source + (" › " + heading if heading else "")
        lines.append("%d. (%s) %s" % (i, where, text))
    resp["systemMessage"] = "[memsearch] %d related memories" % len(hits)
    resp["hookSpecificOutput"] = {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "\n".join(lines),
    }
    return resp


# ---------------------------------------------------------------------------
# Stop / SubagentStop：parse → summarize → 追加 memory/*.md → index → 时间戳
# ---------------------------------------------------------------------------

def on_stop(payload, ctx, event):
    if payload.get("stop_hook_active") is True:
        return {"continue": True}

    transcript = payload.get("transcript_path") or ""
    if not transcript or not os.path.isfile(transcript):
        return {"continue": True}

    try:
        with open(transcript, encoding="utf-8", errors="replace") as f:
            line_count = sum(1 for _ in f)
    except Exception:
        line_count = 0
    if line_count < 3:
        return {"continue": True}

    meta = ctx["parse_mod"].parse_last_turn(transcript)
    if meta["sentinel"] or not meta["text"]:
        return {"continue": True}

    session_id = os.path.splitext(os.path.basename(transcript))[0]
    today = time.strftime("%Y-%m-%d")
    now = time.strftime("%H:%M")
    memory_dir = os.path.join(ctx["memsearch_dir"], "memory")
    memory_file = os.path.join(memory_dir, "%s.md" % today)

    # 懒写标题判定（只读检查 memory 文件）：无本 session 锚点则先补 ## Session 标题
    need_session_heading = True
    if os.path.isfile(memory_file):
        try:
            with open(memory_file, encoding="utf-8", errors="replace") as f:
                if ("session:%s" % session_id) in f.read():
                    need_session_heading = False
        except Exception:
            pass

    _stop_live(ctx, meta, transcript, memory_dir, memory_file,
               session_id, now, need_session_heading)
    return {"continue": True}


def _stop_live(ctx, meta, transcript, memory_dir, memory_file,
               session_id, now, need_session_heading):
    """Stop 主流程：summarize → 追加 memory/*.md → index → 写隐含时间戳。"""
    memsearch_dir = ctx["memsearch_dir"]
    collection = _derive_collection(ctx["project_dir"])
    ms = _find_memsearch()

    # --- summarize（provider 缺失给清晰错误 bullet，不静默降级 — §3.4/A4）---
    summary = ""
    failure = ""
    prov = _resolve_summarize_provider()
    if not ms:
        failure = "memsearch CLI not found on PATH"
    elif not prov["provider"]:
        failure = "no LLM provider configured in ~/.memsearch/config.toml"
    else:
        rc, out = _run(
            [ms, "summarize", "--plugin", "openclaw",
             "--agent-name", OPENCLAW_AGENT_NAME],
            input_text=meta["text"],
            timeout=110,
            env=_child_env(memsearch_dir),
        )
        if rc in (-124, 124):
            failure = "summarizer timed out"
        elif rc != 0:
            failure = "summarizer exited with status %d" % rc
        elif not out.strip():
            failure = "summarizer returned empty output"
        else:
            summary = out.strip()
    if failure:
        summary = (
            "- Memory summary unavailable: %s; transcript content was omitted."
            " Use the transcript anchor for progressive disclosure." % failure
        )

    # --- 追加当日 memory/*.md（懒写 ## Session 标题 + 锚点）---
    parts = []
    if need_session_heading:
        parts.append("\n## Session %s\n" % now)
    parts.append("### %s" % now)
    parts.append(
        "<!-- session:%s turn:%s transcript:%s -->"
        % (session_id, meta["last_user_id"], transcript)
    )
    parts.append(summary)
    parts.append("")
    try:
        os.makedirs(memory_dir, exist_ok=True)
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write("\n".join(parts))
    except Exception:
        return  # 写不进记忆就不索引（无增量）

    # --- index（同步）→ 成功后写隐含时间戳（§7-12）---
    if ms:
        rc, _ = _run(
            [ms, "index", memory_dir, "-c", collection],
            timeout=300,
            env=_child_env(memsearch_dir),
        )
        if rc == 0:
            _write_index_ts(memsearch_dir)
            # detached 点火到期 maintenance（due-state 节流，未到期近似 no-op）
            _bg_run(
                MAINT_PID_NAME,
                [
                    sys.executable,
                    os.path.join(SCRIPT_DIR, "handler.py"),
                    "--maintenance",
                    ctx["project_dir"],
                    memsearch_dir,
                ],
                memsearch_dir,
            )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    # 隐藏子命令：SessionStart 的后台索引进程（detached，独立执行后写时间戳）
    if len(sys.argv) > 1 and sys.argv[1] == "--index-and-stamp":
        if len(sys.argv) >= 5:
            return _index_and_stamp(sys.argv[2], sys.argv[3], sys.argv[4])
        return 1

    # 隐藏子命令：Stop 后的到期 maintenance + 技能蒸馏（detached）
    if len(sys.argv) > 1 and sys.argv[1] == "--maintenance":
        if len(sys.argv) >= 4:
            return _maintenance(sys.argv[2], sys.argv[3])
        return 1

    # C4 防重入：维护/摘要点火链里的子进程不再触发本插件
    if os.environ.get("MEMSEARCH_DISABLE") == "1":
        _respond({"continue": True})
        return 0

    try:
        raw = sys.stdin.read() or ""
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    event = payload.get("hook_event_name") or "unknown"
    project_dir = _project_dir(payload)
    memsearch_dir = os.path.join(project_dir, ".memsearch")
    ctx = {
        "project_dir": project_dir,
        "memsearch_dir": memsearch_dir,
        "parse_mod": None,
    }

    try:
        if event in ("Stop", "SubagentStop"):
            ctx["parse_mod"] = _load_parse()
            response = on_stop(payload, ctx, event)
        elif event == "SessionStart":
            response = on_session_start(payload, ctx)
        elif event == "UserPromptSubmit":
            response = on_user_prompt_submit(payload, ctx)
        else:
            response = {"continue": True}
    except Exception:
        # C2：任何解析/分派异常都不卡死会话
        response = {"continue": True}

    _respond(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())
