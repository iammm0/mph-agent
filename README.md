<div align="center">
  <h1>Multiphysics Modeling Agent</h1>
  <h2>wechat:physicisthacker2030</h2>
  <h2>本人本科原本是学习应用物理学的，但是今年26届毕业转行做计算机，这个项目是我毕业设计自我选题实践内容中的一部分，有物理系背景和计算机背景交叉领域的同好与前辈欢迎添加我的微信与我闲聊，在此之前，已经有对该项目感兴趣的友友向我提议想要建个群来交流这个项目</h2>
  <p>面向 COMSOL 的开源建模智能体：规划层 + 本地 Java API 执行</p>
  <p>
    <img src="https://img.shields.io/badge/mph--agent-1.1.2-green.svg" alt="mph-agent 1.1.2">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue.svg" alt="python >=3.10"></a>
    <img src="https://img.shields.io/badge/COMSOL-6.3-orange.svg" alt="COMSOL 6.3">
    <img src="https://img.shields.io/badge/Tauri-2.10.2-555555.svg" alt="Tauri 2.10.2">
    <img src="https://img.shields.io/badge/React-18.3.1-61DAFB.svg" alt="React 18.3.1">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="license MIT"></a>
    <img src="https://img.shields.io/badge/platform-Windows%20x64%20%7C%20macOS%20Apple%20Silicon-orange.svg" alt="platform Windows x64 | macOS Apple Silicon">
  </p>
  <p><b>中文</b> | English (coming soon)</p>
</div>

Multiphysics Modeling Agent（mph-agent）是一个面向 COMSOL Multiphysics 的开源建模智能体，目标是把自然语言建模需求变成可执行、可追踪、可复现的 `.mph` 模型文件。

这条分支把 COMSOL 调用链做成“规划层 + 本地 ActionExecutor + 官方 Java API”的主路径，重点解决三件事：

1. 让自然语言需求稳定落到可执行的 COMSOL 步骤。
2. 让几何、材料、物理、网格、研究、求解按阶段写回 `.mph`，形成可追踪的建模闭环。
3. 让失败信息、阶段产物和调试轨迹更适合开源协作与社区复现。

> 当前项目以 **COMSOL Multiphysics 6.3** 为目标版本研发、测试与维护；案例库、文档知识库、路径示例与相关提示均以 **6.3** 为准。

---

## 这条分支做了什么

执行层的核心是本地 Java API，而不是把 claw-code 当成建模骨架：

- **本地 ActionExecutor**：`agent/react/action_executor.py` 将几何、材料、物理、网格、研究、求解等步骤交给 `JavaAPIController` / `COMSOLRunner`。
- **官方 Java API**：`agent/executor/java_api_controller.py` 覆盖材料、物理场、研究、静态 API 与节点对象调用。
- **按阶段写回模型**：每个阶段生成独立 `.mph`，并维护 `_latest` 副本，便于回溯和排错。
- **材料规划更稳**：`agent/planner/material_agent.py` 对常见材料做更直接的快速识别。
- **端到端回归脚本**：`scripts/agent_build_loop.py` 反复跑完整建模流程并保存失败事件日志。
- **可选 claw-code 旁路**：记忆压缩、token 预算、计划镜像默认可用；`CLAW_CODE_ENABLED=1` 时才把少数扩展动作交给内嵌调度器。

---

## 目录

- [重要声明 / Disclaimer](#重要声明--disclaimer)
- [简介](#简介)
- [功能特性](#功能特性)
- [可选 claw-code 旁路](#可选-claw-code-旁路)
- [界面预览](#界面预览)
- [安装](#安装)
- [环境配置](#环境配置)
- [使用方法](#使用方法)
- [文档](#文档)
- [开发与调试](#开发与调试)
- [常见问题](#常见问题)
- [许可证](#许可证)

## 重要声明 / Disclaimer

使用本软件即表示您已知晓并同意以下条款及 [LICENSE](LICENSE) 中的补充声明：

1. **本项目为独立开源工具，与 COMSOL 官方无任何关联、非官方产品、非官方插件。**
2. **本项目仅通过 COMSOL 官方公开 API 进行自动化调用与脚本生成，不包含任何 COMSOL 核心代码、不破解、不修改、不绕过 COMSOL 许可机制。**
3. **使用本工具的前提是用户已拥有合法、正版的 COMSOL Multiphysics 软件许可。**
4. **任何使用盗版、破解、未授权版本 COMSOL 的行为，均违反 COMSOL 最终用户许可协议及相关法律法规，由此产生的一切法律责任、风险与后果由使用者自行承担，与本项目作者及贡献者无关。**
5. **本项目仅用于学习、科研与合法合规的工程自动化用途，请勿用于商业侵权或非法用途。**

---

## 简介

mph-agent 基于 ReAct（Reasoning & Acting）架构：先理解建模需求，再规划步骤，随后通过本地 Java API 执行 COMSOL 操作，并通过观察结果继续迭代，最终生成可直接在 COMSOL 中打开的 `.mph` 文件。

claw-code 相关能力是旁路工具（记忆压缩、token 预算、计划镜像），以及可选的少数扩展动作调度，不是默认执行层。

项目提供 **Tauri 2.10.2 + React 18.3.1 桌面应用** 与 **源码运行**，不提供 Python 包分发；支持多种 LLM 后端（DeepSeek、Kimi、Ollama、OpenAI 兼容等）。

---

## 功能特性

- **ReAct 闭环**：推理、执行、观察、迭代，自动生成 `.mph`
- **讨论模式**：`/discuss` 进入增量式结构化讨论，逐步确认建模意图后再规划
- **计划模式**：`/plan` 触发结构化计划与澄清问答，确认后再执行
- **多 LLM 后端**：DeepSeek、Kimi、OpenAI 兼容、Ollama
- **COMSOL 集成**：面向 COMSOL Multiphysics 6.3 的 Java API、节点 API 与官方索引调用
- **可选 claw-code 旁路**：记忆压缩、token 预算、计划镜像；显式开启后才调度少数扩展 COMSOL 动作
- **JavaAPI 操作目录**：`/ops_catalog` 列出可用的 COMSOL Java API 封装操作
- **案例库**：`/case_library` 同步官网案例索引；`/case` 从本地 `.mph` 提取结构化操作 JSON
- **技能库**：内置 Markdown 技能（`agent/skills/library/`），支持向量检索与注入；`/skills` 管理本地技能
- **文档知识库**：可从本机 COMSOL 官方 HTML/TXT 文档构建本地 SQLite/FTS 知识库
- **桌面应用**：Tauri 2.10.2 + React 18.3.1，支持主题切换、推理任务、记忆管理、LLM 与 COMSOL 环境配置
- **上下文与记忆**：对话历史、摘要式记忆、自定义别名，提升多轮解析准确性

---

## 可选 claw-code 旁路

建模主链路是 `ActionExecutor` + `JavaAPIController`。仓库里仍保留嵌入式 claw-code 运行时，但默认不参与 COMSOL 执行。

仍然默认启用的旁路能力：

1. **记忆压缩**：会话摘要走 claw-code 风格的 compact / microcompact。
2. **token 预算**：推理阶段估算 prompt 预算，桌面端展示 TokenBudgetCard。
3. **计划镜像**：把 `ReActTaskPlan` 同步到 PlanRuntime，便于审计和桌面展示。

仅当 `CLAW_CODE_ENABLED=1` 时，`import_geometry`、`create_selection`、`export_results`、`call_official_api` 才会交给 `ClawCodeComsolDispatcher`。几何、材料、物理、网格、研究、求解始终走本地实现。dispatcher 失败不会自动 fallback 到 Java API。

按阶段写回 `.mph` 和 `scripts/agent_build_loop.py` 回归脚本属于主链路，不依赖该开关。

---

## 界面预览

当前仓库已移除大部分流程图展示资源，因此这里不再保留图片墙。桌面端界面主要包含以下几类页面：

- 主界面：输入建模需求、查看执行状态、读取输出模型
- 推理过程页：展示 ReAct 推理、规划、执行与观察的阶段信息
- 配置页：LLM 后端、COMSOL 路径、Java 环境与主题设置
- 记忆页：查看摘要式记忆、历史上下文与别名管理
- 帮助页：查看斜杠命令、环境诊断与常用操作说明
- 结果页：查看生成的 `.mph` 文件与阶段性产物

---

## 安装

本项目**仅提供桌面版安装包与源码运行**，不提供 Python 包（pip install）分发。

### 环境要求

- **Python >= 3.10**（来自 `pyproject.toml` 的 `requires-python`）
- **COMSOL Multiphysics 6.3**（已安装；官方测试范围：Windows x64 / macOS Apple Silicon）
- **Java JDK 8+**（与 COMSOL 兼容；项目也可使用内置 JDK 11）

主要前端/桌面依赖以锁文件为准：

- **Tauri 2.10.2**（`desktop/src-tauri/Cargo.lock`）
- **React 18.3.1**（`desktop/package-lock.json`）
- **Vite 6.4.1**（`desktop/package-lock.json`）
- **TypeScript 5.6.3**（`desktop/package-lock.json`）

### 方式一：桌面版（推荐，Windows x64 / macOS Apple Silicon）

从 [GitHub Releases](https://github.com/iammm0/mph-agent/releases) 下载对应安装包（tag 格式为 `desktop-v*`）：

- **Windows x64（AMD64）**：exe 或 msi
- **macOS Apple Silicon**：dmg

安装包内已包含 **Java 11**，无需单独安装 Python 或 JDK。暂不提供 Linux 桌面版，也不支持 Windows ARM 与 macOS Intel。

### 方式二：从源码运行

```bash
git clone https://github.com/iammm0/mph-agent.git
cd mph-agent

# 使用 uv 安装依赖（需先安装 uv: https://docs.astral.sh/uv/）
uv sync

# 启动桌面应用（无参数即启动 Tauri 桌面端）
uv run python cli.py
```

开发模式下需安装 [Node.js](https://nodejs.org/) 与 [Rust](https://rustup.rs/)；若已构建过桌面端，会优先运行本地可执行文件。

若您从旧名称 `comsol-agent` 迁移，请将命令与配置中的 `comsol-agent` 改为 `mph-agent`，桌面端需重新安装以更新产品名与 identifier。

安装与构建细节见 [docs/getting-started/INSTALL.md](docs/getting-started/INSTALL.md)。

---

## 环境配置

安装后需配置 **LLM 后端** 与 **COMSOL 路径**（桌面应用内也可在设置页配置）。

### 必需

1. **LLM**：设置 `LLM_BACKEND`（如 `deepseek`、`kimi`、`ollama`、`openai-compatible`），并配置对应 API Key / URL。
2. **COMSOL**：设置 `COMSOL_JAR_PATH`（也可留空，程序会尝试探测本机默认安装位置）  
   - **Windows x64 / COMSOL 6.3**：`C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins`
   - **macOS Apple Silicon / COMSOL 6.3**：`/Applications/COMSOL63/Multiphysics/plugins`

### 可选

- **JAVA_HOME**：不配置时优先用系统 Java，或使用项目内置 JDK 11（自动下载到 `runtime/java`）
- **JAVA_DOWNLOAD_MIRROR**：国内可设 `tsinghua` 使用清华镜像
- **JAVA_SKIP_AUTO_DOWNLOAD**：设为 `1` 时禁止自动下载内置 JDK，仅使用已存在的 `JAVA_HOME` 或 `runtime/java`
- **COMSOL_NATIVE_PATH**：手动指定含 JNI `.dll`/`.dylib` 的本地库目录；留空时 Windows 推导 `bin/win64`，Apple Silicon 推导 `bin/macarm64`
- **MODEL_OUTPUT_DIR**：模型输出目录，默认项目根目录下的 `models`

### claw-code 相关配置（可选）

建模默认不走 claw-code 调度。旧 `.env` 若仍写 `CLAW_CODE_ENABLED=1`，会覆盖代码默认值。

- `CLAW_CODE_ENABLED`：是否把少数扩展动作交给 claw-code 调度，默认关闭（`0`）
- `CLAW_CODE_MAX_TURNS`：单步执行轮数上限，默认 `12`
- `CLAW_CODE_TIMEOUT_SECONDS`：单步执行超时时间，默认 `120`
- `CLAW_CODE_MODEL`：显式指定 claw-code 使用的模型
- `CLAW_CODE_BASE_URL`：显式指定 claw-code 的 OpenAI 兼容接口地址
- `CLAW_CODE_API_KEY`：显式指定 claw-code 的 API Key

如果这些值为空，opt-in 调度会尽量复用当前桌面端所选 LLM 后端。保存桌面 LLM 配置不会强制打开该开关。

### 配置方式

**使用 `.env` 文件（推荐）**：在项目根目录创建 `.env`，例如：

```env
LLM_BACKEND=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3
COMSOL_JAR_PATH=C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins
# macOS Apple Silicon 示例：
# COMSOL_JAR_PATH=/Applications/COMSOL63/Multiphysics/plugins
CLAW_CODE_ENABLED=0
CLAW_CODE_MAX_TURNS=12
CLAW_CODE_TIMEOUT_SECONDS=120
```

更多后端示例（DeepSeek、Kimi、OpenAI 兼容等）见 [docs/getting-started/llm-backends.md](docs/getting-started/llm-backends.md)。  
在桌面应用内输入 **`/doctor`** 可做环境诊断，详见 [docs/getting-started/CONFIG.md](docs/getting-started/CONFIG.md)。

### 可选：导入本机 COMSOL 文档知识库

项目不会把 COMSOL 在线文档整站直接打包进仓库或发行包；如果你本机已安装官方文档，可将其导入为本地知识库，供 Agent 在推理时自动检索：

```bash
# source 可传 COMSOL Multiphysics 根目录、plugins 目录，或 doc 目录
uv run python scripts/import_comsol_docs.py "C:\Program Files\COMSOL\COMSOL63\Multiphysics"
```

也可在 `.env` 中设置：

```dotenv
COMSOL_DOC_PATH=C:\Program Files\COMSOL\COMSOL63\Multiphysics
```

默认索引文件输出到 `data/doc_knowledge/comsol_docs.db`。导入完成后，现有 planner / ReAct 流程会自动把检索到的文档片段注入 prompt，无需额外开关。

---

## 使用方法

### 桌面应用（推荐）

```bash
uv run python cli.py
```

- **默认模式**：底部输入框输入自然语言建模需求，直接生成 COMSOL 模型
- **计划模式**：输入 `/plan` 切换为仅解析为 JSON；`/run` 切回默认模式
- **斜杠命令**：`/demo`、`/doctor`、`/context`、`/backend`、`/output`、`/help`、`/quit`

### Python API（源码运行下使用）

在项目根目录执行 `uv sync` 后，可从源码导入使用：

```python
from agent.react.react_agent import ReActAgent

react_agent = ReActAgent(max_iterations=10)
model_path = react_agent.run("创建一个宽1米、高0.5米的矩形")
print(f"模型已生成: {model_path}")
```

更多示例见 [docs/getting-started/EXAMPLE.md](docs/getting-started/EXAMPLE.md)。

---

## 文档

- 文档索引：[docs/README.md](docs/README.md)
- 安装与配置：[INSTALL.md](docs/getting-started/INSTALL.md)、[CONFIG.md](docs/getting-started/CONFIG.md)
- 架构设计：[architecture.md](docs/architecture/architecture.md)
- 技能系统：[agent/skills/library/README.md](agent/skills/library/README.md)
- Agent 运行说明：[AGENT.md](AGENT.md)

---

## 项目结构

```
mph-agent/
├── README.md, AGENT.md, pyproject.toml, uv.lock, env.example
├── desktop/          # Tauri 2.10.2 + React 18.3.1 桌面应用
├── docs/             # 文档索引见 docs/README.md
├── agent/            # 主流程包（见 AGENT.md）；内含 prompts/、schemas/、skills/
│   ├── prompts/      # 提示词模板（planner / executor / react）
│   ├── schemas/      # 数据模型（geometry, physics, study, task）
│   └── skills/       # 技能加载代码；library/ 为 SKILL.md 技能包
├── data/             # 技能索引数据库（默认 data/skills.db）
├── scripts/          # 构建、回归与调试脚本
├── assets/           # README 与文档用截图
└── tests/            # 单元测试
```

---

## 架构详图

仓库目前不再依赖流程图图片展示架构。核心结构可以用文字概括为：

- **输入层**：桌面端、CLI、Python API
- **编排层**：`run/`、`core/`、`react/`，负责路由、会话和 ReAct 编排
- **规划层**：`planner/`，把自然语言拆成几何、材料、物理、研究等结构化计划
- **执行层**：`executor/`，负责 COMSOL 调用与官方 Java API；claw-code 调度为可选旁路
- **知识层**：`agent/skills/library/`、文档知识库与 `agent/prompts/` 注入
- **支撑层**：`utils/`、配置、日志、Java 运行时与环境检查

如果你需要更细的职责说明，可以直接查看 [AGENT.md](AGENT.md) 和 [docs/architecture/](docs/architecture/) 下的设计文档。

---

## 开发与调试

- 运行 `scripts/agent_build_loop.py` 可以做端到端回归，自动保存每次尝试的事件日志和摘要
- `/doctor` 可以快速检查 LLM、COMSOL、Java 与本地输出目录是否配置正确
- 如果要追踪执行结果，优先看 `logs/agent-build-loop/` 和每次生成的阶段性 `.mph` 文件
- 详细 Agent 内部职责说明见 [AGENT.md](AGENT.md)

---

## 常见问题

### 为什么我看到了多个 `.mph` 文件？

因为这条分支会按阶段保存模型副本，例如几何、材料、物理、研究、求解和 `_latest`，这样更便于定位问题和恢复。

### 为什么还保留官方 Java API？

因为官方 Java API 就是默认执行层。claw-code 只在显式开启时处理少数扩展动作，失败时不会自动改走 Java API。

### 为什么需要额外的 `claw-code` 配置？

默认不需要。只有打开 `CLAW_CODE_ENABLED=1`，或要把 opt-in 调度接到独立模型/服务时，才需要指定模型、Base URL 和 API Key；不配时它会尽量沿用当前 LLM 后端。

---

## 许可证

MIT License。详见 [LICENSE](LICENSE)。
