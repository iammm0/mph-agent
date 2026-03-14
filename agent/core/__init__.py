"""核心基础设施：基类、事件、路由、会话、依赖注入。"""
from agent.core.base import BaseAgent
from agent.core.events import EventBus, Event, EventType
from agent.core.router import route
from agent.core.session import SessionOrchestrator
from agent.core.dependencies import (
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
