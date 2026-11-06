"""Plan stage handler with free discuss/plan/run interleaving."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from agent.utils.logger import get_logger
from agent.schemas.task import (
    ClarifyingAnswer,
    ClarifyingOption,
    ClarifyingQuestion,
    DiscussionCard,
    GlobalDefinitionPlan,
)

logger = get_logger(__name__)

_CONFIRM_PLAN_KEYWORDS = (
    "确认计划",
    "确认规划",
    "开始建模",
    "进入建模",
    "执行计划",
    "plan confirmed",
)

_REGENERATE_PLAN_KEYWORDS = (
    "重新规划",
    "重新生成计划",
    "重建计划",
    "改写计划",
    "改写规划",
    "重做规划",
    "regenerate plan",
    "rebuild plan",
)


def _card_has_content(card: DiscussionCard) -> bool:
    return any(
        [
            card.physical_principles,
            card.target_metrics,
            card.known_inputs,
            card.unknowns,
            card.assumptions,
            card.risks,
            card.candidate_solutions,
        ]
    )


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    t = (text or "").strip().lower()
    return any(k in t for k in keywords)


def _extract_param_name_value(text: str) -> Optional[tuple[str, str]]:
    m = re.search(r"\b([A-Za-z_]\w*)\s*=\s*([^\s,;，；]+)", text or "")
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def _build_clarifying_questions(card: DiscussionCard) -> List[ClarifyingQuestion]:
    questions: List[ClarifyingQuestion] = []
    idx = 1

    for item in card.unknowns:
        if not item.strip():
            continue
        questions.append(
            ClarifyingQuestion(
                id=f"q_unknown_{idx}",
                source=f"unknowns:{idx}",
                text=f"针对未知项“{item}”，规划阶段采用哪种处理策略？",
                type="single",
                options=[
                    ClarifyingOption(
                        id="opt_recommended",
                        label="先按推荐默认值推进 (Recommended)",
                        value="recommended",
                        recommended=True,
                    ),
                    ClarifyingOption(
                        id="opt_need_quant",
                        label="必须先给出定量输入",
                        value="need_quantified_input",
                    ),
                    ClarifyingOption(
                        id="opt_sensitivity",
                        label="先做参数敏感性分析",
                        value="sensitivity_first",
                    ),
                ],
            )
        )
        idx += 1

    risk_idx = 1
    for item in card.risks:
        if not item.strip():
            continue
        questions.append(
            ClarifyingQuestion(
                id=f"q_risk_{risk_idx}",
                source=f"risks:{risk_idx}",
                text=f"针对风险“{item}”，优先采用哪种风险控制策略？",
                type="single",
                options=[
                    ClarifyingOption(
                        id="opt_recommended",
                        label="先按保守网格/边界设置推进 (Recommended)",
                        value="conservative_default",
                        recommended=True,
                    ),
                    ClarifyingOption(
                        id="opt_tight_validation",
                        label="先加强验证再执行",
                        value="tight_validation_first",
                    ),
                    ClarifyingOption(
                        id="opt_fast_iteration",
                        label="先快速迭代后收敛",
                        value="fast_iteration_first",
                    ),
                ],
            )
        )
        risk_idx += 1

    return questions


def _extract_global_definitions(card: DiscussionCard) -> List[GlobalDefinitionPlan]:
    out: List[GlobalDefinitionPlan] = []
    seen = set()
    for item in [*card.known_inputs, *card.assumptions]:
        pair = _extract_param_name_value(item)
        if not pair:
            continue
        name, value = pair
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(GlobalDefinitionPlan(name=name, value=value, description=item))
    return out


class PlanModeHandler:
    """
    Plan stage entry.

    Rules:
    1) discussion card is optional (empty card + user_input is enough);
    2) unresolved clarifications block plan confirmation;
    3) confirmed plan is persisted to plan.json + plan_readable.md;
    4) rewriting / regenerating clears plan_confirmed (invalidate-and-redo).
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

    def _build_plan_from_discussion(self, card: DiscussionCard, user_input: str) -> Dict[str, Any]:
        if _card_has_content(card):
            discuss_text = "\n".join(
                [
                    "讨论结论：",
                    f"物理原理: {', '.join(card.physical_principles) or '未提供'}",
                    f"目标指标: {', '.join(card.target_metrics) or '未提供'}",
                    f"已知输入: {', '.join(card.known_inputs) or '未提供'}",
                    f"假设: {', '.join(card.assumptions) or '未提供'}",
                    f"候选方案: {', '.join(card.candidate_solutions) or '未提供'}",
                    f"规划补充: {user_input or '无'}",
                ]
            )
        else:
            discuss_text = (user_input or "").strip() or "请根据会话上下文生成建模规划。"

        orchestrator = self._get_orchestrator()
        memory_context = (
            self.context_manager.get_context_for_planner()
            if hasattr(self.context_manager, "get_context_for_planner")
            else ""
        )
        task_plan, _ctx, serial_plan = orchestrator.run(discuss_text, context=memory_context)

        if hasattr(task_plan, "model_dump"):
            plan_dict = task_plan.model_dump()
        elif hasattr(task_plan, "dict"):
            plan_dict = task_plan.dict()
        else:
            plan_dict = {}

        if getattr(serial_plan, "plan_description", None):
            plan_dict["plan_description"] = serial_plan.plan_description
        if getattr(serial_plan, "steps", None):
            plan_dict["steps"] = [
                {
                    "step_index": getattr(s, "step_index", i + 1),
                    "agent_type": getattr(s, "agent_type", ""),
                    "description": getattr(s, "description", ""),
                    "input_snippet": getattr(s, "input_snippet", ""),
                }
                for i, s in enumerate(serial_plan.steps)
            ]

        questions = _build_clarifying_questions(card)
        globals_plan = _extract_global_definitions(card)

        plan_dict["discussion_card_ref"] = card.card_id
        plan_dict["global_definitions"] = [g.model_dump() for g in globals_plan]
        plan_dict["clarifying_questions"] = [q.model_dump() for q in questions]
        plan_dict["unresolved_clarifications"] = [q.id for q in questions]
        plan_dict["answered_clarifications"] = []
        plan_dict["plan_confirmed"] = False
        return plan_dict

    @staticmethod
    def _build_readable_plan(plan_dict: Dict[str, Any], card: DiscussionCard) -> str:
        lines: List[str] = []
        lines.append("# 建模规划（Plan Stage）")
        lines.append("")
        lines.append("## 讨论结论引用")
        lines.append(f"- discussion_card_ref: `{card.card_id}`")
        lines.append(f"- physical_principles: {len(card.physical_principles)} 条")
        lines.append(f"- target_metrics: {len(card.target_metrics)} 条")
        lines.append(f"- known_inputs: {len(card.known_inputs)} 条")
        lines.append(f"- unknowns: {len(card.unknowns)} 条")
        lines.append(f"- risks: {len(card.risks)} 条")
        lines.append("")

        lines.append("## 执行链")
        for step in plan_dict.get("steps", []) or []:
            lines.append(
                f"- [{step.get('step_index', '?')}] {step.get('agent_type', 'step')}: {step.get('description', '')}"
            )
        lines.append("")

        lines.append("## 全局定义")
        globals_plan = plan_dict.get("global_definitions") or []
        if globals_plan:
            for item in globals_plan:
                lines.append(
                    f"- `{item.get('name')}` = `{item.get('value')}`"
                    + (f" [{item.get('unit')}]" if item.get("unit") else "")
                )
        else:
            lines.append("- 暂无")
        lines.append("")

        unresolved = plan_dict.get("unresolved_clarifications") or []
        lines.append("## 澄清状态")
        lines.append(f"- unresolved_clarifications: {len(unresolved)}")
        lines.append(f"- plan_confirmed: {bool(plan_dict.get('plan_confirmed'))}")
        lines.append("")

        if plan_dict.get("plan_description"):
            lines.append("## 规划说明")
            lines.append(str(plan_dict.get("plan_description")))
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _apply_clarifying_answers(
        self, plan_dict: Dict[str, Any], answers_payload: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        questions = {
            q["id"]: q
            for q in (plan_dict.get("clarifying_questions") or [])
            if isinstance(q, dict) and q.get("id")
        }
        unresolved = list(plan_dict.get("unresolved_clarifications") or [])
        answered = list(plan_dict.get("answered_clarifications") or [])

        for raw in answers_payload:
            try:
                ans = ClarifyingAnswer.model_validate(raw)
            except Exception:
                continue
            if ans.question_id not in questions:
                continue
            if ans.question_id in unresolved:
                unresolved.remove(ans.question_id)
            if ans.question_id not in answered:
                answered.append(ans.question_id)

            selected = ", ".join(ans.selected_option_ids or [])
            note = f"{ans.question_id}: {selected or 'none'}"
            if ans.supplement_text:
                note += f"; supplement={ans.supplement_text}"
                plan_dict.setdefault("global_definitions", [])
                parsed = _extract_param_name_value(ans.supplement_text)
                if parsed:
                    name, value = parsed
                    exists = {
                        str(x.get("name", "")).lower()
                        for x in plan_dict.get("global_definitions", [])
                        if isinstance(x, dict)
                    }
                    if name.lower() not in exists:
                        plan_dict["global_definitions"].append(
                            GlobalDefinitionPlan(
                                name=name,
                                value=value,
                                description=f"from_clarification:{ans.question_id}",
                            ).model_dump()
                        )
            plan_dict.setdefault("clarification_log", []).append(note)

        plan_dict["unresolved_clarifications"] = unresolved
        plan_dict["answered_clarifications"] = answered
        if not unresolved:
            plan_dict["plan_confirmed"] = True
        return plan_dict

    def process(
        self,
        user_input: str,
        clarifying_answers: Optional[List[Dict[str, Any]]] = None,
        *,
        auto_confirm: bool = False,
    ) -> Tuple[str, Optional[Dict[str, Any]], bool, Optional[List[Dict[str, Any]]]]:
        """
        Returns:
        - reply_text
        - plan_dict
        - plan_confirmed
        - clarifying_questions (when still unresolved)

        auto_confirm: when True and clarifications are resolved, lock plan without
        requiring user keywords like「确认计划」(used by chat pipeline).
        """

        user_input = (user_input or "").strip()
        discussion_raw = self.context_manager.load_discussion_card()
        if discussion_raw:
            try:
                card = DiscussionCard.model_validate(discussion_raw)
            except Exception:
                logger.warning("discussion card corrupt; falling back to empty card")
                card = DiscussionCard()
        else:
            card = DiscussionCard()

        current = self.context_manager.load_plan()
        want_regen = _contains_any(user_input, _REGENERATE_PLAN_KEYWORDS)
        was_confirmed = bool(current and current.get("plan_confirmed"))
        # Rewrite when: no draft yet, explicit regenerate, or confirmed plan + new non-confirm input.
        substantive_rewrite = (
            was_confirmed
            and bool(user_input)
            and not _contains_any(user_input, _CONFIRM_PLAN_KEYWORDS)
            and not clarifying_answers
        )
        if current is None or want_regen or substantive_rewrite:
            if was_confirmed and hasattr(self.context_manager, "invalidate_confirmed_plan"):
                self.context_manager.invalidate_confirmed_plan()
            plan_dict = self._build_plan_from_discussion(card, user_input)
        else:
            plan_dict = current

        if clarifying_answers:
            if was_confirmed and hasattr(self.context_manager, "invalidate_confirmed_plan"):
                # Answering clarifications after confirm means re-open; re-confirm when closed.
                self.context_manager.invalidate_confirmed_plan()
                plan_dict["plan_confirmed"] = False
            plan_dict = self._apply_clarifying_answers(plan_dict, clarifying_answers)

        unresolved = list(plan_dict.get("unresolved_clarifications") or [])
        if unresolved and not clarifying_answers:
            self.context_manager.save_plan(plan_dict)
            self.context_manager.save_plan_readable(self._build_readable_plan(plan_dict, card))
            questions = plan_dict.get("clarifying_questions") or []
            return (
                "规划草案已生成。存在未澄清项，请先回答澄清问题。",
                plan_dict,
                False,
                questions,
            )

        if unresolved and clarifying_answers:
            self.context_manager.save_plan(plan_dict)
            self.context_manager.save_plan_readable(self._build_readable_plan(plan_dict, card))
            questions = [
                q
                for q in (plan_dict.get("clarifying_questions") or [])
                if isinstance(q, dict) and q.get("id") in unresolved
            ]
            return (
                "已记录本轮澄清，但仍有未闭环问题，请继续补充。",
                plan_dict,
                False,
                questions,
            )

        if (
            auto_confirm
            or _contains_any(user_input, _CONFIRM_PLAN_KEYWORDS)
            or clarifying_answers
        ):
            plan_dict["plan_confirmed"] = True

        self.context_manager.save_plan(plan_dict)
        self.context_manager.save_plan_readable(self._build_readable_plan(plan_dict, card))

        confirmed = bool(plan_dict.get("plan_confirmed"))
        if confirmed:
            return (
                "建模规划已确认，已写入 plan.json 与 plan_readable.md。",
                plan_dict,
                True,
                None,
            )
        return (
            "规划草案已更新。所有澄清项已完成，可继续执行建模。",
            plan_dict,
            False,
            None,
        )
