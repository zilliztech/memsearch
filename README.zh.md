<h1 align="center">
  <img src="assets/logo-icon.jpg" alt="" width="100" valign="middle">
  &nbsp;
  memsearch
</h1>

<p align="center">
  <strong>专为 AI 编程智能体 (Coding Agents) 打造的跨平台语义长期记忆引擎。</strong>
</p>

<p align="center">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/memsearch/"><img src="https://img.shields.io/pypi/v/memsearch?style=flat-square&color=blue" alt="PyPI"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/claude-code/"><img src="https://img.shields.io/badge/Claude_Code-plugin-c97539?style=flat-square&logo=claude&logoColor=white" alt="Claude Code"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/codex/"><img src="https://img.shields.io/badge/Codex-plugin-ff6b35?style=flat-square" alt="Codex"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/dsh/"><img src="https://img.shields.io/badge/DeepSeek_Harness-plugin-4d6bfe?style=flat-square" alt="DeepSeek Harness"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/openclaw/"><img src="https://img.shields.io/badge/OpenClaw-plugin-4a9eff?style=flat-square" alt="OpenClaw"></a>
  <a href="https://zilliztech.github.io/memsearch/platforms/opencode/"><img src="https://img.shields.io/badge/OpenCode-plugin-22c55e?style=flat-square" alt="OpenCode"></a>
  <a href="https://pypi.org/project/memsearch/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://github.com/zilliztech/memsearch/blob/main/LICENSE"><img src="https://img.shields.io/github/license/zilliztech/memsearch?style=flat-square" alt="License"></a>
  <a href="https://github.com/zilliztech/memsearch/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/zilliztech/memsearch/test.yml?branch=main&style=flat-square" alt="Tests"></a>
  <a href="https://zilliztech.github.io/memsearch/"><img src="https://img.shields.io/badge/docs-memsearch-blue?style=flat-square" alt="Docs"></a>
  <a href="https://github.com/zilliztech/memsearch/stargazers"><img src="https://img.shields.io/github/stars/zilliztech/memsearch?style=flat-square" alt="Stars"></a>
  <a href="https://discord.com/invite/FG6hMJStWu"><img src="https://img.shields.io/badge/Discord-chat-7289da?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://x.com/zilliz_universe"><img src="https://img.shields.io/badge/follow-%40zilliz__universe-000000?style=flat-square&logo=x&logoColor=white" alt="X (Twitter)"></a>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/427b7152-bc16-408c-a8b0-59a2b05fd1e0" alt="memsearch demo" width="800">
</p>

## 📰 最新动态

- **可选 Jev 重排序 (Reranking)** — 通过 TypeSafe API 使用 Jev 模型重排记忆检索结果，无需在本地下载大模型。参见[配置文档](docs/home/configuration.md#optional-remote-reranking)与[中英文评估基准](evaluation/reranking-evaluation.md)。
- **DeepSeek Harness (DSH) 全面支持** — MemSearch 为 [DeepSeek Harness (DSH)](https://zilliztech.github.io/memsearch/platforms/dsh/) 提供全自动会话捕获、每轮首步记忆注入、原生 Skill 召回、后台维护以及只读记忆浏览器。
- **从记忆提炼技能 (Skills from Memory)** — MemSearch 现能从您高频重复的工作流中自动提炼出可复用、可安装的 Agent 技能（作为第三层“程序性记忆”），并在后台持续演进更新。参见[技能提炼章节](#-从记忆提炼技能-skills-from-memory)。
- **进阶长期记忆维护** — 可选的后台定时维护任务，持续跨会话刷新长效项目摘要 `PROJECT.md` 与用户偏好画像 `USER.md`。

---

### 💡 为什么选择 memsearch？

- 🌐 **多平台互通，单一真相源** — 记忆在 [Claude Code](plugins/claude-code/README.md)、[Codex](plugins/codex/README.md)、[DeepSeek Harness](plugins/dsh/README.md)、[OpenClaw](plugins/openclaw/README.md) 以及 [OpenCode](plugins/opencode/README.md) 之间无缝流转。在一个智能体中的对话，即刻成为所有其他智能体可检索的上下文，零配置打通。
- 👥 **面向 Agent 用户**，只需安装对应插件即可开箱即用；**面向 Agent 开发者**，提供完整的 [CLI 命令行工具](https://zilliztech.github.io/memsearch/cli/) 与 [Python SDK](https://zilliztech.github.io/memsearch/python-api/)，将记忆与 Harness 工程轻松集成进专属 Agent。
- 📄 **Markdown 是唯一真相源** — 灵感源自 [OpenClaw](https://github.com/openclaw/openclaw)。您的长期记忆就是最纯粹的 `.md` 文件：人类可直接阅读、可自由编辑、可受 Git 版本控制。Milvus 仅作为“影子索引（Shadow Index）”，可随时一键全量重建。
- 🔍 **渐进式检索 + 混合搜索 + 智能去重 + 实时同步** — 三层渐进式召回（搜索 → 展开全文 → 原生会话钻取）；稠密向量 + BM25 稀疏分词 + RRF 倒数排名融合；SHA-256 内容哈希防重复嵌入；内置文件监听器实现毫秒级自动建库。

---

## 🧑‍💻 面向 Agent 用户：极速上手

选择您正在使用的 Agent 平台，安装对应插件即可。插件会在会话结束时自动沉淀上下文，并在需要时提供语义召回，零额外心智负担。

<details open>
<summary><h3>针对 Claude Code 用户</h3></summary>

```bash
# 安装插件
/plugin marketplace add zilliztech/memsearch
/plugin install memsearch
# 重启 Claude Code 激活插件
```

重启后正常对话即可，插件会自动捕获每一轮对话记录。

**验证是否正常工作** — 对话几轮后，检查您的记忆目录：
```bash
ls .memsearch/memory/          # 会按天生成对应的 .md 文件
cat .memsearch/memory/$(date +%Y-%m-%d).md
```

**主动召回记忆**：
```
/memory-recall 我们之前讨论过 Redis 缓存，当时选定的 TTL 是多少？
```
或者自然对话提问，Claude 感知到需要历史背景时会自动触发该技能。

> 📖 [Claude Code 插件文档](https://zilliztech.github.io/memsearch/platforms/claude-code/) · [常见故障排查](https://zilliztech.github.io/memsearch/platforms/claude-code/troubleshooting/)

</details>

<details open>
<summary><h3>针对 Codex 用户</h3></summary>

```bash
# 安装
git clone --depth 1 https://github.com/zilliztech/memsearch.git
bash memsearch/plugins/codex/scripts/install.sh
codex --yolo  # 允许 ONNX 嵌入模型网络访问
```

安装后照常对话，Hooks 会自动捕获并提炼每一轮对话。

**召回记忆**：
```
$memory-recall 我们之前讨论过部署方案，当时是怎么决定的？
```

> 📖 [Codex 插件文档](https://zilliztech.github.io/memsearch/platforms/codex/)

</details>

<details open>
<summary><h3>针对 DeepSeek Harness (DSH) 用户</h3></summary>

```bash
# 在 DSH 对应配置中安装插件
uv tool install "memsearch[onnx]"
dsh plugin --profile web add @zilliz/memsearch-dsh
# 重启 DSH，或打开新会话即可
```

安装完成后照常使用。已完成的会话会自动提炼存入记忆，并在每轮思考第 1 步时自动检索并注入相关上下文（未命中时零 Token 损耗）。

Web 界面还自带居中自适应的 **MemSearch 悬浮 Dock 面板**，可直观审阅提炼的技能草稿并预览 `.memsearch/` 记忆文件树。

> 📖 [DeepSeek Harness 插件文档](plugins/dsh/README.zh.md)

</details>

<details>
<summary><h3>针对 OpenClaw 用户</h3></summary>

```bash
# 从 ClawHub 安装
openclaw plugins install --force clawhub:memsearch
openclaw config set plugins.entries.memsearch.hooks.allowConversationAccess true
openclaw config set plugins.entries.memsearch.hooks.allowPromptInjection true
openclaw gateway restart
```

> 📖 [OpenClaw 插件文档](https://zilliztech.github.io/memsearch/platforms/openclaw/) · [ClawHub 插件主页](https://clawhub.ai/plugins/memsearch)

</details>

<details>
<summary><h3>针对 OpenCode 用户</h3></summary>

在 `~/.config/opencode/opencode.json` 中配置：
```json
{ "plugin": ["@zilliz/memsearch-opencode"] }
```

后台守护进程会自动捕获并同步对话记录。

> 📖 [OpenCode 插件文档](https://zilliztech.github.io/memsearch/platforms/opencode/)

</details>

---

### ⚙️ 通用配置 (全平台共享)

所有平台的插件共用同一套底层的 memsearch 配置文件。一次配置，全平台通用。

#### 1. 向量嵌入模型 (Embedding)

默认使用 **本地 ONNX bge-m3** — 完全在本地 CPU 上运行，零 API Key、零费用。首次启动时会自动从 HuggingFace 下载模型（约 558 MB）。

```bash
memsearch config set embedding.provider onnx     # 默认推荐：本地免费，免 API Key
memsearch config set embedding.provider openai   # 需配置 OPENAI_API_KEY
memsearch config set embedding.provider ollama   # 本地 Ollama 模型
```

> 📖 查看所有支持的模型供应商：[配置文档 — Embedding Provider](https://zilliztech.github.io/memsearch/home/configuration/#embedding-provider)

#### 2. Milvus 向量数据库后端

通过修改 `milvus.uri`（以及可选的 `milvus.token`）轻松切换部署模式：

- **Milvus Lite（默认）** — 零配置单文件，极速开箱即用：
  ```bash
  memsearch config get milvus.uri   # 默认保存在 ~/.memsearch/milvus.db
  ```

- ⭐ **Zilliz Cloud（全托管推荐）** — 云端全托管，提供[永久免费额度](https://cloud.zilliz.com/signup?utm_source=github&utm_medium=referral&utm_campaign=memsearch-readme)：
  ```bash
  memsearch config set milvus.uri "https://in03-xxx.api.gcp-us-west1.zillizcloud.com"
  memsearch config set milvus.token "你的API密钥"
  ```

- **自建 Milvus Docker 实例**（团队及高级用户）：
  ```bash
  memsearch config set milvus.uri http://localhost:19530
  ```

---

### 🧠 进阶记忆维护与技能提炼

#### 长效记忆维护 (PROJECT.md / USER.md)

除了按天记录的日志外，智能体还能在后台维护两份高层级总结文件：
- **`PROJECT.md`**：记录项目的长效架构决策、技术选型、演进脉络及后续待办；
- **`USER.md`**：记录您的个人工作偏好、沟通习惯与固定需求。

默认处于关闭状态。您只需在对话框对 AI 说一句：*“开启 MemSearch 的 PROJECT.md 和 USER.md 维护”*，AI 就会通过 `memory-config` 技能自动帮您配置完毕。

#### 🛠️ 从记忆提炼技能 (Skills from Memory)

MemSearch 的第三层能力是**程序性记忆（Procedural Memory）**：AI 能将您高频重复的多步操作提炼成标准化的 Agent 技能。全程自然语言交互：

- *“把我们刚才的操作提炼成一个技能。”* — AI 会钻取刚才的真实会话记录生成准确的 `SKILL.md` 草稿，存入候选区等待您审阅安装。
- *“查看当前有哪些技能候选，帮我安装部署那个。”* — AI 会列出草稿，经您确认后安装到对应目录，立即可用。

<p align="center">
  <img width="1086" height="752" alt="MemSearch 技能提炼演示" src="https://github.com/user-attachments/assets/39a90f1c-54e3-4c7a-b168-051f0e096d39">
</p>

提炼出的技能统一保存在受 Git 追踪的 `.memsearch/skill-candidates/` 中，遵循开放的 [Agent Skills](https://agentskills.io) 规范，完全支持在 Claude Code、Codex、DSH、OpenClaw、OpenCode 之间互相迁移通用。

---

## 🛠️ 面向 Agent 开发者：SDK 与内核架构

除了现成的插件，memsearch 提供了完整的 **Python API 与 CLI 工具**，方便您将长期记忆引擎植入自定义 Agent 或 RAG 管道中。

### 🏗️ 架构全景

```
┌──────────────────────────────────────────────────────────────┐
│                  🧑‍💻 面向 Agent 用户 (Plugins 插件层)         │
│ Claude Code · Codex · DSH · OpenClaw · OpenCode · 自建应用    │
│                              │                               │
├────────────────────────────┬─────────────────────────────────┤
│  🛠️ 面向 Agent 开发者       │  基于底层能力开发定制 ↓          │
│  ┌─────────────────────────┴──────────────────────────────┐  │
│  │           memsearch CLI / Python API SDK               │  │
│  │      index · search · expand · watch · compact         │  │
│  └─────────────────────────┬──────────────────────────────┘  │
│  ┌─────────────────────────┴──────────────────────────────┐  │
│  │         核心引擎: 分块 (Chunker) → 向量化 → Milvus      │  │
│  │         混合检索 (BM25 + Dense 稠密向量 + RRF 融合)    │  │
│  └────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│  📄 Markdown 文件体系 (唯一真相源)                           │
│  memory/2026-03-27.md · memory/2026-03-26.md · ...           │
└──────────────────────────────────────────────────────────────┘
```

### 3 层渐进式召回流程

```
用户提问: "我们之前讨论过的 Redis 缓存 TTL 是多少？"
                     │
                     ▼
  L1  memsearch search "Redis TTL"     → 返回语义排名的文本切片 (Chunks)
                     │ (需要周围更多上下文？)
                     ▼
  L2  memsearch expand <chunk_hash>    → 展开返回完整的 Markdown 段落
                     │ (需要回溯原始完整会话？)
                     ▼
  L3  parse-transcript <session.jsonl> → 定位钻取当时的完整多轮对话原始交互
```

---

### 🐍 Python API 快速上手

```python
from memsearch import MemSearch

# 初始化记忆实例
mem = MemSearch(paths=["./memory"])

# 建立索引
await mem.index()

# 语义混合检索
results = await mem.search("Redis 配置", top_k=3)
print(results[0]["content"], results[0]["score"])
```

<details>
<summary><b>完整示例：为 OpenAI 智能体赋予长期记忆</b>（点击展开）</summary>

```python
import asyncio
from datetime import date
from pathlib import Path
from openai import OpenAI
from memsearch import MemSearch

MEMORY_DIR = "./memory"
llm = OpenAI()
mem = MemSearch(paths=[MEMORY_DIR])

def save_memory(content: str):
    """将交互记录追加至当天的记忆日记中"""
    p = Path(MEMORY_DIR) / f"{date.today()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"\n{content}\n")

async def agent_chat(user_input: str) -> str:
    # 1. 回想 — 从长期记忆中召回相关背景
    memories = await mem.search(user_input, top_k=3)
    context = "\n".join(f"- {m['content'][:200]}" for m in memories)

    # 2. 思考 — 注入记忆上下文并请求大模型
    resp = llm.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": f"你具备以下历史记忆背景：\n{context}"},
            {"role": "user", "content": user_input},
        ],
    )
    answer = resp.choices[0].message.content

    # 3. 记忆 — 保存本次交互并增量同步索引
    save_memory(f"## {user_input}\n{answer}")
    await mem.index()
    return answer

async def main():
    save_memory("## 团队设定\n- Alice: 前端负责人\n- Bob: 后端负责人")
    save_memory("## 架构决策\n我们决定在缓存层选型 Redis 而非 Memcached。")
    await mem.index()

    print(await agent_chat("我们的前端负责人是谁？"))
    print(await agent_chat("我们选定了哪种缓存方案？"))

asyncio.run(main())
```

</details>

---

### ⌨️ CLI 常用指令速查

```bash
# 初始化配置向导
memsearch config init

# 手动构建/更新索引
memsearch index ./memory/
memsearch index ./memory/ --force        # 全量重新向量化

# 语义混合检索
memsearch search "Redis caching"
memsearch search "auth flow" --top-k 10 --json-output

# 展开切片全文
memsearch expand <chunk_hash>

# 后台实时监听与增量同步
memsearch watch ./memory/

# 统计与重置
memsearch stats                          # 查看已索引的切片数
memsearch reset --yes                    # 清空全部索引并重建
```

---

## 🔗 相关链接

- 📖 [官方完整文档](https://zilliztech.github.io/memsearch/) — 指南、API 参考与架构规范
- 🔌 [全平台插件中心](https://zilliztech.github.io/memsearch/platforms/) — Claude Code、Codex、DSH、OpenClaw、OpenCode
- 💡 [设计哲学](https://zilliztech.github.io/memsearch/design-philosophy/) — 为什么以 Markdown 为本位？为什么选择 Milvus？
- 🗄️ [Milvus 向量数据库](https://milvus.io/) | [Zilliz Cloud](https://cloud.zilliz.com/signup?utm_source=github&utm_medium=referral&utm_campaign=memsearch-readme) — 底层向量检索引擎

---

## 🤝 贡献与社区

欢迎提交 Issue、功能建议与 Pull Request！开发环境搭建与测试规范请参阅 [贡献指南 (Contributing Guide)](CONTRIBUTING.md)。

欢迎加入官方 [Discord 社区](https://discord.com/invite/FG6hMJStWu) 与全球开发者交流！

---

## 📄 开源许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
