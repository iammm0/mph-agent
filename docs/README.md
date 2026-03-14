# 文档索引

本目录按用途对文档做了分类，便于查阅与维护。

## 一、入门与使用（getting-started/）

安装、配置与日常使用相关。

| 文档 | 说明 |
|------|------|
| [INSTALL.md](getting-started/INSTALL.md) | 安装与构建：分发包构建、安装步骤、环境要求 |
| [CONFIG.md](getting-started/CONFIG.md) | 配置说明：环境变量、.env、COMSOL/JAVA/LLM 配置与验证 |
| [EXAMPLE.md](getting-started/EXAMPLE.md) | 示例命令：可直接复制的 run/plan/exec/demo 等命令，含复杂几何测试提示词 |
| [CONTEXT.md](getting-started/CONTEXT.md) | 上下文管理：对话历史、摘要、别名与上下文查看 |
| [ollama-setup.md](getting-started/ollama-setup.md) | Ollama 本地部署与配置 |
| [llm-backends.md](getting-started/llm-backends.md) | LLM 后端：DeepSeek、Kimi、Ollama、OpenAI 兼容等 |
| [DEBUG-BRIDGE.md](getting-started/DEBUG-BRIDGE.md) | **调试 Python Bridge**：出现「Bridge process closed unexpectedly」时如何开启 stderr 与 traceback 调试 |
| [BRIDGE-WORKING-SNAPSHOT.md](getting-started/BRIDGE-WORKING-SNAPSHOT.md) | Bridge 可用版本快照：用于回退对比排查 |

## 二、架构与设计（architecture/）

系统架构、ReAct 模式、工作流程与 Agent 职责（含架构图与流程图）。

| 文档 | 说明 |
|------|------|
| [architecture.md](architecture/architecture.md) | **架构设计**：系统总体架构图、路由与 ReAct 模式图、Think→Act→Observe→Iterate 工作流程图、核心组件与技术栈 |
| [agent-design.md](architecture/agent-design.md) | Agent 设计：ReActAgent、ReasoningEngine、ActionExecutor、Planner/Executor、Q&A 与 Summary 职责与协作 |
| [comsol-modules-and-context.md](architecture/comsol-modules-and-context.md) | 三模块与共享上下文：模型开发器/App 开发器/模型管理器、EventBus、SessionContext 扩展设想 |

### 设计范式（agent-design-skills/）

与具体业务无关的程序设计经验，可在其他项目中复用。

| 文档 | 说明 |
|------|------|
| [agent-design-skills/README.md](agent-design-skills/README.md) | 设计范式目录索引 |
| [agent-architecture.md](agent-design-skills/agent-architecture.md) | 多智能体架构、路由分发 |
| [skill-plugin-system.md](agent-design-skills/skill-plugin-system.md) | 技能/插件系统 |
| [session-and-events.md](agent-design-skills/session-and-events.md) | 会话与 EventBus |
| [cli-and-dependencies.md](agent-design-skills/cli-and-dependencies.md) | CLI 与依赖注入 |
| [config-and-env.md](agent-design-skills/config-and-env.md) | 配置与环境 |
| [prompt-management.md](agent-design-skills/prompt-management.md) | 提示词管理 |
| [react-and-tool-calling.md](agent-design-skills/react-and-tool-calling.md) | ReAct 与工具调用 |
| [commit-conventions.md](agent-design-skills/commit-conventions.md) | 提交规范 |

## 三、参考（reference/）

COMSOL API 与外部参考链接。

| 文档 | 说明 |
|------|------|
| [comsol-api-notes.md](reference/comsol-api-notes.md) | COMSOL API 笔记：Java API 用法、模型/几何接口要点 |
| [comsol-api-links.md](reference/comsol-api-links.md) | COMSOL 官方文档与版本链接 |

## 四、项目维护（project/）

贡献、发布与协作规范。

| 文档 | 说明 |
|------|------|
| [CONTRIBUTING.md](project/CONTRIBUTING.md) | 贡献指南：分支、提交信息、PR 与文档约定 |
| [PUBLISH.md](project/PUBLISH.md) | 发布流程：版本、构建与 PyPI 发布 |
