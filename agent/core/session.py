"""会话编排器：按路由调用 Q&A 或 Planner → Core → Summary，依赖注入 EventBus/Console/get_agent。"""
from typing import Optional, Callable, Any

from agent.core.events import EventBus, EventType
from agent.core.dependencies import get_agent, get_event_bus, get_router


class SessionOrchestrator:
    """
    会话编排：根据路由结果调用 Q&A 或「Planner → Core → Summary」。
    依赖通过构造函数注入；若未传入则使用 dependencies 默认。
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        get_agent_fn: Optional[Callable[[str], Any]] = None,
        router_fn: Optional[Callable[[str], str]] = None,
        console: Optional[Any] = None,
    ):
        self._bus = event_bus or get_event_bus()
        self._get_agent = get_agent_fn or get_agent
        self._route = router_fn or get_router()
        self._console = console

    def run(self, user_input: str, output_filename: Optional[str] = None, **kwargs: Any) -> str:
        """
        处理一轮用户输入。返回助手回复或执行结果摘要。
        """
        route_result = self._route(user_input)

        if route_result == "qa":
            self._bus.emit_type(EventType.TASK_PHASE, {"phase": "qa"})
            qa = self._get_agent("qa")
            reply = qa.process(user_input, **kwargs)
            self._bus.emit_type(EventType.CONTENT, {"content": reply})
            return reply

        # technical: Core (ReAct) 执行，再 Summary 摘要
        self._bus.emit_type(EventType.PLAN_START, {"user_input": user_input})
        core = self._get_agent("core")
        try:
            result_path = core.run(user_input, output_filename)
            self._bus.emit_type(
                EventType.EXEC_RESULT,
                {"status": "success", "model_path": str(result_path)},
            )
            summary_agent = self._get_agent("summary")
            summary = summary_agent.process(
                f"模型已生成: {result_path}",
                **kwargs,
            )
            self._bus.emit_type(EventType.CONTENT, {"content": summary})
            return summary or str(result_path)
        except Exception as e:
            self._bus.emit_type(EventType.ERROR, {"message": str(e)})
            summary_agent = self._get_agent("summary")
            summary = summary_agent.process(f"执行失败: {e}", **kwargs)
            return summary or str(e)

    def run_plan_only(self, user_input: str, **kwargs: Any) -> Any:
        """仅执行 Planner，返回结构化计划（如 GeometryPlan）。"""
        self._bus.emit_type(EventType.PLAN_START, {"user_input": user_input})
        planner = self._get_agent("planner")
        plan = planner.parse(user_input, context=kwargs.get("context"))
        self._bus.emit_type(EventType.PLAN_END, {"plan": str(type(plan).__name__)})
        return plan
