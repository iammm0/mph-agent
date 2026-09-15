# AGENT 运行说明

这份文档面向维护者、贡献者和需要理解执行链的人。它说明 mph-agent 的关键路径：规划之后，COMSOL 动作默认由本地 `ActionExecutor` + `JavaAPIController` 执行。claw-code 是可选旁路，不是建模主链路。

## 核心结构

- `agent/react/action_executor.py` 把高层计划分发给具体动作，并调用官方 Java API。
- `agent/executor/java_api_controller.py` 负责材料、物理场、研究、静态调用和节点级操作。
- `agent/executor/comsol_runner.py` 负责 JVM 与 COMSOL 运行时。
- `agent/planner/material_agent.py` 对基础材料做更稳的快速识别，减少 LLM 在简单输入上的漂移。
- `scripts/agent_build_loop.py` 负责端到端回归、失败复现和日志留档。

默认路径：

`自然语言 -> 计划 -> ActionExecutor 本地动作 -> Java API -> 阶段模型写回 -> 继续迭代`

## 关键执行链

1. 用户在桌面端或 CLI 中输入建模需求。
2. `ReActAgent` 或规划器生成结构化计划。
3. `ActionExecutor.execute()` 按 `step.action` 调用对应本地 handler（几何、材料、物理、网格、研究、求解，以及导入/选择/导出/官方 API）。
4. handler 通过 `JavaAPIController` / `COMSOLRunner` 写回阶段 `.mph`，并把结果写入上下文和事件流。

几何 / 材料 / 物理 / 网格 / 研究 / 求解 **始终**走本地实现，与 `CLAW_CODE_ENABLED` 无关。

## 可选：claw-code 调度

`CLAW_CODE_ENABLED` 默认关闭。仅当显式设为 `1` 时，下列四个动作才会走 `ClawCodeComsolDispatcher.dispatch()`：

- `import_geometry`
- `create_selection`
- `export_results`
- `call_official_api`

这不是失败后的自动兜底：dispatcher 出错就返回错误，**不会**再自动改走 `JavaAPIController`。排查 opt-in 调度时看 `details` 里的 `stop_reason`、`final_output`、`turns`、`tool_calls`。

与执行无关、始终可用的旁路能力：

- 记忆压缩（`agent/clawcode_bridge/memory.py`）
- token 预算（`agent/clawcode_bridge/budget.py`）
- 计划镜像（`agent/clawcode_bridge/plan_sync.py`）

## 阶段性模型策略

`ActionExecutor` 为不同阶段生成独立路径，例如：

- `*_geometry.mph`
- `*_material.mph`
- `*_physics.mph`
- `*_mesh.mph`
- `*_study.mph`
- `*_solve.mph`
- `*_latest.mph`

这样做的好处是每一步产物可见，出错时更容易定位，也便于回归测试和社区复现。

## 调试建议

1. 先看 `logs/agent-build-loop/` 是否已有一次完整回归记录。
2. 再看对应阶段 `.mph` 是否已生成。
3. 然后看 `ActionExecutor` 发出的事件。
4. 最后看 `java_api_controller.py` 的返回内容。只有显式开启 claw-code 时，才需要再看 `clawcode_dispatcher.py`。

## 环境变量

建模依赖原有 COMSOL 与 LLM 配置。claw-code 相关项全部可选，且默认关闭：

- `CLAW_CODE_ENABLED`（默认 `0`；旧 `.env` 若仍写 `1` 会覆盖代码默认值）
- `CLAW_CODE_MAX_TURNS`
- `CLAW_CODE_TIMEOUT_SECONDS`
- `CLAW_CODE_MODEL`
- `CLAW_CODE_BASE_URL`
- `CLAW_CODE_API_KEY`

如果没有显式设置 `CLAW_CODE_MODEL` 和 `CLAW_CODE_BASE_URL`，opt-in 调度会尽量复用当前桌面端选择的 LLM 后端。保存桌面 LLM 配置不会把 `CLAW_CODE_ENABLED` 强制改回 `1`。

## 与 README 的分工

`README.md` 面向外部读者，讲项目是什么、能做什么。

`AGENT.md` 面向维护者，讲内部模块怎么协作、出了问题先看哪里。
