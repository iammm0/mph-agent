"""Plan 模式处理器：多轮交互式形成 plan.json，满意后进入 Core 执行。"""

import json
from typing import Any, Dict, Optional, Tuple

from agent.utils.logger import get_logger

logger = get_logger(__name__)

# 用户表达「开始执行/满意计划」的措辞
_ENTER_CORE_KEYWORDS = (
    "开始建",
    "开始建模",
    "开始仿真",
    "就这样建",
    "就这样执行",
    "可以了",
    "满意",
    "开始执行",
    "进入执行",
    "开始跑",
    "run",
    "execute",
    "go",
)
# 建模相关调整：几何/材料/物理场/研究等
_MODELING_KEYWORDS = (
    "几何", "材料", "物理", "研究", "网格", "求解", "边界", "尺寸", "形状",
    "rectangle", "circle", "block", "cylinder", "heat", "solid", "fluid",
    "稳态", "瞬态", "长方体", "圆柱", "传热", "力学", "添加", "修改", "改成",
)


def _is_enter_core_intent(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) > 80:
        return False
    return any(k in t for k in _ENTER_CORE_KEYWORDS)


def _is_modeling_intent(text: str) -> bool:
    t = (text or "").strip()
    return any(k in t for k in _MODELING_KEYWORDS)


class PlanModeHandler:
    """
    Plan 模式处理器：维护会话级 plan 状态，每轮判断意图后更新计划或返回 QA 回复，
    识别「进入执行」后返回 should_enter_core 与当前 plan.json。
    """

    def __init__(
        self,
        context_manager: Any,
        get_agent: Any,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.context_manager = context_manager
        self.get_agent = get_agent
        self._backend = backend
        self._api_key = api_key
        self._base_url = base_url
        self._ollama_url = ollama_url
        self._model = model

    def _get_orchestrator(self):
        from agent.planner.orchestrator import PlannerOrchestrator

        return PlannerOrchestrator(
            backend=self._backend,
            api_key=self._api_key,
            base_url=self._base_url,
            ollama_url=self._ollama_url,
            model=self._model,
        )

    def process(self, user_input: str) -> Tuple[str, Optional[Dict[str, Any]], bool]:
        """
        处理一轮 Plan 模式用户输入。

        Returns:
            (reply_text, plan_dict, should_enter_core)
            - reply_text: 本轮回复
            - plan_dict: 更新后的计划（可序列化为 plan.json）；若未变更则为当前加载的或 None
            - should_enter_core: 是否应带着当前计划进入 Core 执行
        """
        user_input = (user_input or "").strip()
        current = self.context_manager.load_plan()

        if _is_enter_core_intent(user_input):
            if not current:
                return (
                    "当前还没有可执行的计划，请先描述您的建模需求（几何、材料、物理场、研究等）。",
                    None,
                    False,
                )
            return (
                "已确认计划，将进入建模执行流程。",
                current,
                True,
            )

        if _is_modeling_intent(user_input):
            try:
                orchestrator = self._get_orchestrator()
                memory_context = self.context_manager.get_context_for_planner() if hasattr(self.context_manager, "get_context_for_planner") else ""
                task_plan, _ctx, serial_plan = orchestrator.run(
                    user_input, context=memory_context, shared_context=None
                )
                plan_dict = self._task_plan_to_dict(task_plan, serial_plan)
                self.context_manager.save_plan(plan_dict)
                desc = getattr(serial_plan, "plan_description", None) or "已更新"
                return (
                    f"已根据您的描述更新计划：{desc[:200]}。可继续补充或修改，满意后说「开始建模」进入执行。",
                    plan_dict,
                    False,
                )
            except Exception as e:
                logger.exception("Plan 模式编排失败: %s", e)
                return (
                    f"更新计划时出错：{e}。请换个说法或稍后重试。",
                    current,
                    False,
                )

        # 非建模、非进入执行：走 QA
        try:
            qa = self.get_agent("qa")
            reply = qa.process(user_input)
            return (reply or "请描述建模需求或说「开始建模」进入执行。", current, False)
        except Exception as e:
            logger.warning("Plan 模式 QA 失败: %s", e)
            return ("暂时无法回复，请直接描述建模需求。", current, False)

    @staticmethod
    def _task_plan_to_dict(task_plan: Any, serial_plan: Any) -> Dict[str, Any]:
        """将 TaskPlan 与 SerialPlan 转为可序列化并供 Core 使用的 plan 字典。"""
        if hasattr(task_plan, "model_dump"):
            out = task_plan.model_dump()
        elif hasattr(task_plan, "dict"):
            out = task_plan.dict()
        else:
            out = {}
            for key in ("geometry", "material", "physics", "study"):
                val = getattr(task_plan, key, None)
                if val is None:
                    continue
                if hasattr(val, "model_dump"):
                    out[key] = val.model_dump()
                elif hasattr(val, "to_dict"):
                    out[key] = val.to_dict()
                else:
                    out[key] = val
        if serial_plan is not None:
            if getattr(serial_plan, "plan_description", None):
                out["plan_description"] = serial_plan.plan_description
            if getattr(serial_plan, "steps", None):
                out["steps"] = [
                    {
                        "step_index": getattr(s, "step_index", i + 1),
                        "agent_type": getattr(s, "agent_type", ""),
                        "description": getattr(s, "description", ""),
                        "input_snippet": getattr(s, "input_snippet", ""),
                    }
                    for i, s in enumerate(serial_plan.steps)
                ]
        return out
