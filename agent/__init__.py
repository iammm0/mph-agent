"""
Agent 模块 - 按子包组织：
- core: 基类、事件、路由、会话、依赖注入
- planner: 规划（几何/材料/物理/研究）
- react: ReAct 执行
- executor: COMSOL 运行与 Java API
- agents: Q&A、Summary 等单例 Agent
- memory: 会话记忆与异步更新
- run: do_run/do_plan/do_exec 与 TUI 桥接
- tools: 工具注册表
- utils: 配置、日志、LLM、prompt 等
- skills: 技能加载与注入
"""
from agent.core import (
    BaseAgent,
    EventBus,
    Event,
    EventType,
    route,
    SessionOrchestrator,
    get_agent,
    get_settings,
    get_context_manager,
    get_prompt_manager,
    get_event_bus,
    get_router,
)

__all__ = [
    "BaseAgent",
    "EventBus",
    "Event",
    "EventType",
    "route",
    "SessionOrchestrator",
    "get_agent",
    "get_settings",
    "get_context_manager",
    "get_prompt_manager",
    "get_event_bus",
    "get_router",
]
