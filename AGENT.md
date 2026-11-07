# AGENT 运行说明

面向维护者：mph-agent 把自然语言变成阶段 `.mph`。COMSOL **建模**动作一律走本地 `ActionExecutor` + `JavaAPIController`。
可选后处理后端：[MPh](https://github.com/MPh-py/MPh)（`uv sync --extra mph`，`MPH_BACKEND=auto|on|off`），用于参数读写、evaluate、CSV 导出；见 `agent/executor/mph_backend.py`。

默认路径：

`自然语言 -> 计划 -> ActionExecutor -> Java API -> 阶段模型写回 -> 继续迭代`

## 关键文件

- `agent/react/action_executor.py`：把计划分发给几何、材料、物理、网格、研究、求解等动作
- `agent/executor/java_api_controller.py`：官方 Java API
- `agent/executor/comsol_runner.py`：JVM 与 COMSOL 运行时
- `scripts/agent_build_loop.py`：端到端回归

阶段产物：`*_geometry.mph`、`*_material.mph`、`*_physics.mph`、`*_mesh.mph`、`*_study.mph`、`*_solve.mph`、`*_latest.mph`。

## 旁路工具

会话记忆压缩、token 预算、计划镜像走 `agent/clawcode_bridge/`，底层只保留精简的 `agent/clawcode/`（compact / token / plan_runtime），不参与 COMSOL 执行。

## 错误分析

执行失败时 `IterationController` 会调用 `AnalysisAgent`：交叉查阅 skill / 本地文档库 / 案例库 / 规则与计划上下文，提出多个修复角度并按置信度依次尝试，避免只在同一条错误路径上死磕。

## 调试

1. `logs/agent-build-loop/`
2. 对应阶段 `.mph`
3. `ActionExecutor` 事件
4. `java_api_controller.py` 返回值

`README.md` 面向使用者。本文面向内部模块怎么协作。
