"""依赖注入：get_agent、get_settings、get_event_bus 等，CLI 与 API 共用。"""
from typing import Literal, Optional, Dict, Any, Callable

from agent.utils.config import get_settings as _get_settings
from agent.utils.context_manager import get_context_manager as _get_context_manager
from agent.utils.prompt_manager import get_prompt_manager as _get_prompt_manager
from agent.core.events import EventBus
from agent.core.router import route
from agent.agents.qa_agent import QAAgent
from agent.agents.summary_agent import SummaryAgent
from agent.planner.geometry_agent import GeometryAgent
from agent.planner.material_agent import MaterialAgent
from agent.react.react_agent import ReActAgent

AgentType = Literal["qa", "planner", "material", "core", "summary"]

_agents: Dict[str, Any] = {}
_event_bus: Optional[EventBus] = None


def get_settings():
    """获取配置单例。"""
    return _get_settings()


def get_context_manager(conversation_id=None):
    """获取上下文管理器；conversation_id 不为空时返回该会话专属实例。"""
    return _get_context_manager(conversation_id)


def get_prompt_manager(prompts_dir=None):
    """获取 PromptManager 单例。"""
    return _get_prompt_manager(prompts_dir)


def get_event_bus() -> EventBus:
    """获取 EventBus 单例。"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def get_agent(agent_type: AgentType, **kwargs: Any) -> Any:
    """
    按类型获取 Agent，懒加载并缓存。
    非法类型校验并 raise ValueError（由 CLI/API 转为 SystemExit 或 HTTPException）。
    """
    allowed = ("qa", "planner", "material", "core", "summary")
    if agent_type not in allowed:
        raise ValueError(f"非法 agent_type: {agent_type}，允许: {allowed}")

    # 当 event_bus 非空且为 core 时，不缓存，每次创建新实例（保证每次 run 使用独立 EventBus）
    bypass_cache = agent_type == "core" and kwargs.get("event_bus") is not None

    if agent_type not in _agents or bypass_cache:
        if agent_type == "qa":
            _agents["qa"] = QAAgent(**kwargs)
        elif agent_type == "planner":
            _agents["planner"] = GeometryAgent(**kwargs)
        elif agent_type == "material":
            _agents["material"] = MaterialAgent(**kwargs)
        elif agent_type == "core":
            agent = ReActAgent(**kwargs)
            if bypass_cache:
                return agent
            _agents["core"] = agent
        elif agent_type == "summary":
            _agents["summary"] = SummaryAgent(**kwargs)
    return _agents[agent_type]


def get_router() -> Callable[[str], str]:
    """返回路由函数。"""
    return route
