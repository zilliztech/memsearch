# @zilliz/memsearch-dsh

> DeepSeek Harness (DSH) 官方生态下的跨 Agent 持久化记忆与技能沉淀插件。

[English](README.md) | **简体中文**

为 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH) 提供持久化、跨会话、跨 Agent 的长期记忆能力。底层共享与 Claude Code、Codex、OpenClaw 及 OpenCode 相同的 `.memsearch/memory/` Markdown 存储体系，并由 Milvus 混合检索向量引擎驱动。

```
捕获 (Capture) ── session/event turn/end ──> 总结提炼 (dsh-headless 或 custom-llm) ──> memory/YYYY-MM-DD.md
注入 (Inject)  ── agent/pre-step 第 1 步  ──> 记忆混合检索 ──> 命中召回上下文 (未命中则零 Token 损耗)
回想 (Recall)  ── ctx.skills.register(memory-recall) ──> 检索 → 扩展上下文 → 原生会话钻取
审阅 (Review)  ── Web UI 居中悬浮 Dock ──> 技能候选查看 / 对话审阅 / 一键后台安装
```

---

## 🛠️ 前提条件

- **安装 memsearch 核心工具**：
  ```bash
  uv tool install "memsearch[onnx]"
  ```
- 已配置好的 DSH 运行配置环境（`web` / `headless` / `tui` 等）。
- Node.js >= 22.19（DSH 基础要求）。

---

## 📦 安装方式

### 方式 1：npm 一键安装（推荐）

```bash
dsh plugin --profile web add @zilliz/memsearch-dsh
```

### 方式 2：本地源码安装（开发调试）

```bash
dsh plugin --profile web add /path/to/memsearch/plugins/dsh
```

> 💡 **原理说明**：`dsh plugin` 是基于 pnpm 的插件分发器，它会自动在配置的 `package.json` 中添加 bundle 声明，并通过内置的 `cordis.patch.yml` 将 `memsearch` 服务挂载到 DSH 的 Cordis 依赖树中。

---

## ⚙️ 核心配置参数

插件通过对应 profile 下的 `cordis.patch.yml` 中的 `config` 区块进行配置，所有字段均为可选：

| 配置项 | 类型 | 默认值 | 作用说明 |
| :--- | :--- | :--- | :--- |
| `captureEnabled` | boolean | `true` | 是否在每轮会话结束时捕获记录到记忆库。 |
| `injectEnabled` | boolean | `true` | 是否在 Agent 每轮思考第一步时自动检索并注入相关上下文。 |
| `summarizeEnabled` | boolean | `true` | 写入记忆前是否进行智能总结（失败时写入不可用标记，绝不倾倒原始堆栈）。 |
| `summarizeMode` | string | `auto` | 总结后端模式：`auto`、`dsh-headless` 或 `custom-llm`。 |

### 📝 总结模式 (`summarizeMode`) 说明

- **`auto`**（默认）：
  - 若在 `~/.memsearch/config.toml` 中配置了 `[plugins.dsh.summarize] provider`，则走 `custom-llm` 直连对应大模型；
  - 否则自动使用 `dsh-headless`（复用 DSH 自带的无头 Agent 引擎，开箱即用，零配置）。
- **`dsh-headless`**：启动一次性 DSH headless 实例完成提炼，异步后台执行，完全不阻塞当前会话窗口。
- **`custom-llm`**：轻量级单 Python 进程直连指定模型，不启动 DSH 引擎，适合需要绑定特定轻量模型（如 `deepseek-v4-flash`）的场景。

---

## 🧠 周期性维护任务 (PROJECT.md / USER.md / 技能提炼)

在 `~/.memsearch/config.toml` 中按需开启自动演进功能（默认关闭，安全防偷跑）：

```toml
[plugins.dsh.project_review]
enabled = true            # 自动维护与刷新 .memsearch/PROJECT.md 项目全貌

[plugins.dsh.user_profile]
enabled = true            # 自动分析并维护 .memsearch/USER.md 用户画像与习惯偏好

[plugins.dsh.memory_to_skill]
enabled = true            # 从高频重复操作中自动提炼技能草稿
min_occurrences = 3       # 操作最少重复出现几次才触发提炼（默认 3 次）
```

---

## 💻 网页端界面 (Web UI 浮窗)

在 DSH Web GUI 中，输入框上方会挂载一个自适应居中的 **MemSearch 悬浮 Dock 面板**：

1. **常态（胶囊胶带条）**：
   * 展示当前待审阅的技能候选数量；
   * 点击 **「打开」** 展开详情，点击 **「折叠」** 收起。
2. **展开态（技能候选与文件抽屉）**：
   * **在对话中审阅**：把提炼出的 `SKILL.md` 注入当前对话，让 Agent 协助您复核修改；
   * **一键安装**：后台静默安装到 `~/.agents/skills` 目录；
   * **记忆树浏览器**：点击底部的 `.memsearch/` 抽屉，可直接只读预览记忆库中的 Markdown 日记。
3. **多语言自动切换**：
   * 自动跟随 DSH 系统语言环境：中文系统全量显示地道中文，英文系统显示英文。

---

## 📄 许可证

本项目遵循 MIT 协议开源。
