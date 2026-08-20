<div align="center">
  <h1>Multiphysics Modeling Agent</h1>
  <h2>douyin:mingming</h2>
  <h2>wechat:physicisthacker2030</h2>
  <h2>本人本科原本是学习应用物理学的，但是今年26届毕业转行做计算机，这个项目是我毕业设计自我选题实践内容中的一部分，有物理系背景和计算机背景交叉领域的同好与前辈欢迎添加我的微信与我闲聊，在此之前，已经有对该项目感兴趣的友友向我提议想要建个群来交流这个项目</h2>
  <p>面向 COMSOL 的开源建模智能体，已接入 claw-code 执行链</p>
  <p>
    <img src="https://img.shields.io/badge/mph--agent-1.1.2-green.svg" alt="mph-agent 1.1.2">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue.svg" alt="python >=3.10"></a>
    <img src="https://img.shields.io/badge/COMSOL-6.3-orange.svg" alt="COMSOL 6.3">
    <img src="https://img.shields.io/badge/Tauri-2.10.2-555555.svg" alt="Tauri 2.10.2">
    <img src="https://img.shields.io/badge/React-18.3.1-61DAFB.svg" alt="React 18.3.1">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="license MIT"></a>
    <img src="https://img.shields.io/badge/platform-Windows%20Desktop-orange.svg" alt="platform Windows Desktop">
  </p>
  <p><b>中文</b> | English (coming soon)</p>
</div>

Multiphysics Modeling Agent（mph-agent）是一个面向 COMSOL Multiphysics 的开源建模智能体，目标是把自然语言建模需求变成可执行、可追踪、可复现的 `.mph` 模型文件。

这条 `feat-clawcode-comsol-dispatch` 分支是一次明显的执行层升级。它把原本以内部封装为主的 COMSOL 调用链，重构为“规划层 + claw-code 执行层 + 官方 Java API 兜底”的组合式架构，重点解决三件事：

1. 让 Agent 在单步 COMSOL 操作上具备更强的自治执行能力。
2. 让复杂建模任务可以通过 `claw-code` 反复调度、修复、回写，形成真正的端到端建模闭环。
3. 让失败信息、阶段产物和调试轨迹更适合开源协作与社区复现。

> 当前项目以 **COMSOL Multiphysics 6.3** 为目标版本研发、测试与维护；案例库、文档知识库、路径示例与相关提示均以 **6.3** 为准。

---

## 这条分支做了什么

这一分支的核心变化不是“再包一层 API”，而是把 COMSOL 执行从单一控制器推进到可回路化的工作流：

- **claw-code 内嵌调度**：`agent/executor/clawcode_dispatcher.py` 通过嵌入式 Python claw-code 运行单步 COMSOL 操作，不再依赖外部子进程式拼接。
- **官方 Java API 兜底**：`agent/executor/java_api_controller.py` 增强了材料、物理场、研究、静态 API 与节点对象调用能力，保证复杂场景也能落到 COMSOL 官方接口。
- **按阶段写回模型**：`agent/react/action_executor.py` 将几何、材料、物理、网格、研究、求解等阶段拆分为独立模型产物，便于回溯和排错。
- **材料规划更稳**：`agent/planner/material_agent.py` 对常见材料做了更直接的快速识别，降低 LLM 在基础材料选择上的不确定性。
- **端到端回归脚本**：新增 `scripts/agent_build_loop.py`，支持反复跑完整建模流程并保存每次失败的事件日志，方便社区复现和修复。

如果你把这条分支看作一个里程碑，那么它的关键词不是“更聪明”，而是“更能跑完、也更容易修好”。

---

## 目录

- [重要声明 / Disclaimer](#重要声明--disclaimer)
- [简介](#简介)
- [功能特性](#功能特性)
- [claw-code 接入亮点](#claw-code-接入亮点)
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

mph-agent 基于 ReAct（Reasoning & Acting）架构：先理解建模需求，再规划步骤，随后执行 COMSOL 操作，并通过观察结果继续迭代，最终生成可直接在 COMSOL 中打开的 `.mph` 文件。

这条分支引入 claw-code 后，项目从“能够生成建模指令”进一步走向“能够把建模指令真正跑到底”。也就是说，Agent 不再只停留在规划层，而是可以在单步执行层持续调用、验证和修复，使整个建模过程更接近真实工程工作流。

项目提供 **Tauri 2.10.2 + React 18.3.1 桌面应用** 与 **源码运行**，不提供 Python 包分发；支持多种 LLM 后端（DeepSeek、Kimi、Ollama、OpenAI 兼容等）。

---

## 功能特性

- **ReAct 闭环**：推理、执行、观察、迭代，自动生成 `.mph`
- **讨论模式**：`/discuss` 进入增量式结构化讨论，逐步确认建模意图后再规划
- **计划模式**：`/plan` 触发结构化计划与澄清问答，确认后再执行
- **多 LLM 后端**：DeepSeek、Kimi、OpenAI 兼容、Ollama
- **COMSOL 集成**：面向 COMSOL Multiphysics 6.3 的 Java API、节点 API 与官方索引调用
- **claw-code 内嵌调度**：为单步 COMSOL 操作提供嵌入式执行层，支持更细粒度的自动修复与回写
- **JavaAPI 操作目录**：`/ops_catalog` 列出可用的 COMSOL Java API 封装操作
- **案例库**：`/case_library` 同步官网案例索引；`/case` 从本地 `.mph` 提取结构化操作 JSON
- **技能库**：内置 Markdown 技能（`agent/skills/library/`），支持向量检索与注入；`/skills` 管理本地技能
- **文档知识库**：可从本机 COMSOL 官方 HTML/TXT 文档构建本地 SQLite/FTS 知识库
- **桌面应用**：Tauri 2.10.2 + React 18.3.1，支持主题切换、推理任务、记忆管理、LLM 与 COMSOL 环境配置
- **上下文与记忆**：对话历史、摘要式记忆、自定义别名，提升多轮解析准确性

---

## claw-code 接入亮点

这条分支最值得对外展示的地方，是它把 claw-code 变成了 mph-agent 的执行骨架之一，而不是一个边缘实验功能。

### 1. 单步执行从“调用工具”升级为“执行回路”

`ClawCodeComsolDispatcher` 会把一个 `ExecutionStep`、对应的 `thought`、当前模型路径和目标输出路径打包，交给嵌入式 claw-code 去执行，然后再把结果标准化成 JSON 返回给上层流程。

### 2. 执行结果强约束为 JSON

claw-code 必须只输出一个 JSON 对象，包含 `status`、`message`、`model_path`、`saved_path`、`artifacts`、`details` 等字段。这样上层能稳定处理成功、失败、停止原因和附加产物，不会被自由文本打散。

### 3. 官方 Java API 仍然保留兜底能力

当高层封装不够时，`JavaAPIController` 可以继续走模型对象、节点对象或静态 Java API 的官方入口，保证复杂材料、物理场、研究和保存流程都能落到 COMSOL 原生接口。

### 4. 每个阶段都有自己的模型副本

`ActionExecutor` 会为几何、材料、物理、网格、研究、求解等阶段生成独立的 `.mph` 文件，并维护 `_latest` 副本。这种做法对开源协作尤其友好，因为失败点更清晰，回滚也更直接。

### 5. 提供端到端回归脚本

`scripts/agent_build_loop.py` 可以反复运行同一套建模提示，自动记录事件流和失败摘要，适合做回归测试、问题复现和社区协同修复。

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
- **COMSOL Multiphysics 6.3**（已安装）
- **Java JDK 8+**（与 COMSOL 兼容；项目也可使用内置 JDK 11）

主要前端/桌面依赖以锁文件为准：

- **Tauri 2.10.2**（`desktop/src-tauri/Cargo.lock`）
- **React 18.3.1**（`desktop/package-lock.json`）
- **Vite 6.4.1**（`desktop/package-lock.json`）
- **TypeScript 5.6.3**（`desktop/package-lock.json`）

### 方式一：桌面版（推荐，仅 Windows）

从 [GitHub Releases](https://github.com/iammm0/mph-agent/releases) 下载 Windows 安装包（exe 或 msi，tag 格式为 `desktop-v*`），安装后运行即可。安装包内已包含 **Java 11**，无需单独安装 Python 或 JDK。暂不支持 macOS/Linux 桌面版。

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
2. **COMSOL**：设置 `COMSOL_JAR_PATH`  
   - **COMSOL Multiphysics 6.3**：填 `plugins` 目录，例如  
     `C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins` 或 `/opt/comsol63/multiphysics/plugins`

### 可选

- **JAVA_HOME**：不配置时优先用系统 Java，或使用项目内置 JDK 11（自动下载到 `runtime/java`）
- **JAVA_DOWNLOAD_MIRROR**：国内可设 `tsinghua` 使用清华镜像
- **JAVA_SKIP_AUTO_DOWNLOAD**：设为 `1` 时禁止自动下载内置 JDK，仅使用已存在的 `JAVA_HOME` 或 `runtime/java`
- **COMSOL_NATIVE_PATH**：手动指定含 JNI `.dll`/`.so` 的本地库目录
- **MODEL_OUTPUT_DIR**：模型输出目录，默认项目根目录下的 `models`

### claw-code 相关配置

这条分支新增了内嵌 claw-code 调度配置：

- `CLAW_CODE_ENABLED`：是否启用 claw-code 调度，默认开启
- `CLAW_CODE_MAX_TURNS`：单步执行轮数上限，默认 `12`
- `CLAW_CODE_TIMEOUT_SECONDS`：单步执行超时时间，默认 `120`
- `CLAW_CODE_MODEL`：显式指定 claw-code 使用的模型
- `CLAW_CODE_BASE_URL`：显式指定 claw-code 的 OpenAI 兼容接口地址
- `CLAW_CODE_API_KEY`：显式指定 claw-code 的 API Key

如果这些值为空，嵌入式执行器会尽量复用当前桌面端所选 LLM 后端，降低额外配置成本。

### 配置方式

**使用 `.env` 文件（推荐）**：在项目根目录创建 `.env`，例如：

```env
LLM_BACKEND=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3
COMSOL_JAR_PATH=C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins
CLAW_CODE_ENABLED=1
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
- **执行层**：`executor/`，负责 COMSOL 调用、claw-code 调度和官方 Java API 兜底
- **知识层**：`agent/skills/library/`、文档知识库与 `agent/prompts/` 注入
- **支撑层**：`utils/`、配置、日志、Java 运行时与环境检查

如果你需要更细的职责说明，可以直接查看 [AGENT.md](AGENT.md) 和 [docs/architecture/](docs/architecture/) 下的设计文档。

---

## 开发与调试

- 运行 `scripts/agent_build_loop.py` 可以做端到端回归，自动保存每次尝试的事件日志和摘要
- `/doctor` 可以快速检查 LLM、COMSOL、Java 与本地输出目录是否配置正确
- 如果要追踪 claw-code 的单步执行结果，优先看 `logs/agent-build-loop/` 和每次生成的阶段性 `.mph` 文件
- 详细 Agent 内部职责说明见 [AGENT.md](AGENT.md)

---

## 常见问题

### 为什么我看到了多个 `.mph` 文件？

因为这条分支会按阶段保存模型副本，例如几何、材料、物理、研究、求解和 `_latest`，这样更便于定位问题和恢复。

### 为什么还保留官方 Java API？

因为 claw-code 负责把执行跑起来，官方 Java API 负责把边角能力补齐。两者不是替代关系，而是互补关系。

### 为什么需要额外的 `claw-code` 配置？

如果你希望把 claw-code 接到独立模型或独立服务上，可以显式指定模型、Base URL 和 API Key；如果不配，它会尽量沿用当前 LLM 后端。

---

## 许可证

MIT License。详见 [LICENSE](LICENSE)。
