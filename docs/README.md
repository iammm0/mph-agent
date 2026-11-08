# 文档中心

这里是项目的统一文档入口。文档结构刻意保持为少数几个大类，避免把信息拆得过细，同时保证从使用、架构、参考到协作都能完整覆盖。

## 如何使用这套文档

如果你是第一次接触这个项目，建议按顺序阅读：

1. [README.md](../README.md)
2. [getting-started/INSTALL.md](getting-started/INSTALL.md)
3. [getting-started/CONFIG.md](getting-started/CONFIG.md)
4. [architecture/architecture.md](architecture/architecture.md)
5. [AGENT.md](../AGENT.md)

如果你已经在维护代码，可以把这里当作文档地图使用。

## 一、入门与运行

这部分回答“怎么装、怎么配、怎么跑、怎么排查基础问题”。

| 文档 | 作用 |
|------|------|
| [getting-started/INSTALL.md](getting-started/INSTALL.md) | 安装与源码运行说明，覆盖依赖、桌面端和开发环境准备 |
| [getting-started/CONFIG.md](getting-started/CONFIG.md) | 环境变量、`.env`、LLM、COMSOL、Java 与输出目录配置 |
| [getting-started/EXAMPLE.md](getting-started/EXAMPLE.md) | 常见运行示例与调用方式 |
| [getting-started/CONTEXT.md](getting-started/CONTEXT.md) | 上下文、会话历史、摘要记忆与相关能力说明 |
| [getting-started/llm-backends.md](getting-started/llm-backends.md) | 各类 LLM 后端配置方式 |
| [getting-started/ollama-setup.md](getting-started/ollama-setup.md) | Ollama 本地运行配置 |
| [getting-started/DEBUG-BRIDGE.md](getting-started/DEBUG-BRIDGE.md) | 桌面端 Python Bridge 调试 |
| [getting-started/BRIDGE-WORKING-SNAPSHOT.md](getting-started/BRIDGE-WORKING-SNAPSHOT.md) | Bridge 可用快照说明 |
| [getting-started/BRIDGE-CODE-LOCATIONS.md](getting-started/BRIDGE-CODE-LOCATIONS.md) | Bridge 关键代码位置索引 |

## 二、系统架构

这部分回答“系统由哪些模块组成、数据如何流动、职责如何分层”。

| 文档 | 作用 |
|------|------|
| [architecture/architecture.md](architecture/architecture.md) | 项目整体架构、核心流程和模块边界 |
| [architecture/agent-design.md](architecture/agent-design.md) | Agent 设计、ReAct 角色分工与运行方式 |
| [architecture/comsol-modules-and-context.md](architecture/comsol-modules-and-context.md) | COMSOL 模块与上下文协作关系 |

## 三、参考资料

这部分提供较稳定的查询类文档，适合开发时按需查阅。

| 文档 | 作用 |
|------|------|
| [reference/comsol-api-notes.md](reference/comsol-api-notes.md) | COMSOL API 使用笔记 |
| [reference/comsol-api-links.md](reference/comsol-api-links.md) | COMSOL 官方文档与外部参考链接 |
| [reference/mphb-format.md](reference/mphb-format.md) | `.mphb` 构建过程文件格式与预览说明 |

## 四、项目协作与发布

这部分回答“如何参与维护、如何提交、如何发版”。

| 文档 | 作用 |
|------|------|
| [project/CONTRIBUTING.md](project/CONTRIBUTING.md) | 贡献流程、协作约定与提交建议 |
| [project/PUBLISH.md](project/PUBLISH.md) | 发布与打包流程 |
| [release/RELEASE-v0.1.0.md](release/RELEASE-v0.1.0.md) | 历史版本发布记录 |

## 五、设计模式沉淀

`agent-design-skills/` 不是面向最终用户的“使用文档”，而是从本项目中提炼出的工程设计经验，偏向维护者和架构层复用。

主要内容包括：

- Agent 架构与分工
- 技能 / 插件系统
- Session 与 EventBus
- 配置和环境设计
- Prompt 管理
- ReAct 与工具调用

入口文档见 [agent-design-skills/README.md](agent-design-skills/README.md)。

## 文档边界

当前文档体系按职责分工如下：

- 根目录 `README.md`：面向所有读者，讲项目全貌。
- `docs/README.md`：文档导航页，帮助定位资料。
- `AGENT.md`：面向维护者，讲内部运行链路。
- `BUILD.md`：面向打包和分发，讲桌面构建。
- `agent/README.md`：面向读代码的人，讲 Python 包目录职责。

如果新增文档，优先并入现有分类，而不是继续细分更多层级。
