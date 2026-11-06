"""Tests for discuss/plan free interleaving, invalidate-on-rework, and clarification loop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agent.run.discussion_mode import DiscussionModeHandler
from agent.run.plan_mode import PlanModeHandler
from agent.schemas.task import DiscussionCard


class _DummyContextManager:
    def __init__(self) -> None:
        self._discussion = None
        self._plan = None
        self.plan_readable = ""

    def load_discussion_card(self):
        return self._discussion

    def save_discussion_card(self, payload):
        self._discussion = payload

    def load_plan(self):
        return self._plan

    def save_plan(self, payload):
        self._plan = payload

    def load_plan_readable(self):
        return self.plan_readable or None

    def save_plan_readable(self, text: str):
        self.plan_readable = text

    def invalidate_confirmed_plan(self) -> bool:
        plan = self.load_plan()
        if not plan or not bool(plan.get("plan_confirmed")):
            return False
        plan["plan_confirmed"] = False
        self.save_plan(plan)
        if self.plan_readable and "plan_confirmed: True" in self.plan_readable:
            self.plan_readable = self.plan_readable.replace(
                "plan_confirmed: True", "plan_confirmed: False"
            )
        return True

    def get_context_for_planner(self) -> str:
        return ""


def _fake_orchestrator_run(discuss_text, context=""):
    task_plan = SimpleNamespace(
        model_dump=lambda: {
            "goal": discuss_text[:80],
            "steps": [],
        }
    )
    serial_plan = SimpleNamespace(
        plan_description="mocked plan",
        steps=[
            SimpleNamespace(
                step_index=1,
                agent_type="geometry",
                description="build geometry",
                input_snippet="rect",
            )
        ],
    )
    return task_plan, {}, serial_plan


def test_discussion_soft_finalize_and_reopen_on_new_content():
    ctx = _DummyContextManager()
    handler = DiscussionModeHandler(context_manager=ctx)

    _reply, card = handler.process("传热原理，目标温度低于350K，未知对流系数")
    assert card["finalized"] is False

    _reply2, finalized = handler.process("进入规划")
    assert finalized["finalized"] is True

    reply3, reopened = handler.process("再补充一个风险项：网格可能不收敛")
    assert reopened["finalized"] is False
    assert any("风险" in r or "网格" in r for r in reopened["risks"])
    assert "讨论卡已更新" in reply3


def test_plan_allows_unfinalized_discussion():
    ctx = _DummyContextManager()
    ctx.save_discussion_card(
        DiscussionCard(
            finalized=False,
            physical_principles=["热传导"],
            known_inputs=["边长 1m"],
        ).model_dump(mode="json")
    )
    handler = PlanModeHandler(context_manager=ctx, get_agent=lambda *_args, **_kwargs: None)

    with patch.object(PlanModeHandler, "_get_orchestrator") as mock_get:
        mock_get.return_value = SimpleNamespace(run=_fake_orchestrator_run)
        reply, plan, confirmed, questions = handler.process("开始规划")

    assert plan is not None
    assert confirmed is False
    assert "finalized" not in reply.lower() or "尚未 finalized" not in reply
    assert ctx._plan is not None


def test_plan_builds_from_user_input_without_discussion_card():
    ctx = _DummyContextManager()
    handler = PlanModeHandler(context_manager=ctx, get_agent=lambda *_args, **_kwargs: None)

    with patch.object(PlanModeHandler, "_get_orchestrator") as mock_get:
        mock_get.return_value = SimpleNamespace(run=_fake_orchestrator_run)
        reply, plan, confirmed, _questions = handler.process("创建一个宽1米高0.5米的矩形")

    assert plan is not None
    assert confirmed is False
    assert plan.get("plan_confirmed") is False
    assert "steps" in plan
    assert ctx.plan_readable


def test_discussion_update_invalidates_confirmed_plan():
    ctx = _DummyContextManager()
    ctx.save_plan(
        {
            "discussion_card_ref": "card-1",
            "steps": [],
            "plan_confirmed": True,
            "unresolved_clarifications": [],
            "clarifying_questions": [],
            "answered_clarifications": [],
        }
    )
    ctx.save_plan_readable("# plan\n- plan_confirmed: True\n")
    handler = DiscussionModeHandler(context_manager=ctx)

    _reply, card = handler.process("补充边界条件：左侧温度 300K")
    assert card["finalized"] is False
    assert ctx.load_plan()["plan_confirmed"] is False


def test_plan_returns_clarifying_questions_when_unresolved():
    ctx = _DummyContextManager()
    ctx.save_discussion_card(DiscussionCard(finalized=True).model_dump(mode="json"))
    ctx.save_plan(
        {
            "discussion_card_ref": "card-1",
            "clarifying_questions": [
                {
                    "id": "q1",
                    "text": "请确认边界条件",
                    "type": "single",
                    "options": [
                        {
                            "id": "opt_recommended",
                            "label": "使用推荐值",
                            "value": "recommended",
                            "recommended": True,
                        }
                    ],
                }
            ],
            "unresolved_clarifications": ["q1"],
            "answered_clarifications": [],
            "plan_confirmed": False,
        }
    )
    handler = PlanModeHandler(context_manager=ctx, get_agent=lambda *_args, **_kwargs: None)

    reply, plan, confirmed, questions = handler.process("继续规划")
    assert confirmed is False
    assert plan is not None
    assert isinstance(questions, list) and len(questions) == 1
    assert "澄清" in reply
    assert ctx.plan_readable


def test_plan_answers_close_loop_and_confirm():
    ctx = _DummyContextManager()
    ctx.save_discussion_card(DiscussionCard(finalized=True).model_dump(mode="json"))
    ctx.save_plan(
        {
            "discussion_card_ref": "card-1",
            "clarifying_questions": [
                {
                    "id": "q1",
                    "text": "请确认边界条件",
                    "type": "single",
                    "options": [
                        {
                            "id": "opt_recommended",
                            "label": "使用推荐值",
                            "value": "recommended",
                            "recommended": True,
                        }
                    ],
                }
            ],
            "unresolved_clarifications": ["q1"],
            "answered_clarifications": [],
            "plan_confirmed": False,
        }
    )
    handler = PlanModeHandler(context_manager=ctx, get_agent=lambda *_args, **_kwargs: None)

    reply, plan, confirmed, questions = handler.process(
        "确认计划",
        clarifying_answers=[
            {
                "question_id": "q1",
                "selected_option_ids": ["opt_recommended"],
            }
        ],
    )

    assert confirmed is True
    assert questions is None
    assert plan is not None
    assert plan["plan_confirmed"] is True
    assert plan["unresolved_clarifications"] == []
    assert "确认" in reply


def test_plan_substantive_rewrite_invalidates_confirmed():
    ctx = _DummyContextManager()
    ctx.save_discussion_card(
        DiscussionCard(finalized=True, physical_principles=["热传导"]).model_dump(mode="json")
    )
    ctx.save_plan(
        {
            "discussion_card_ref": "card-1",
            "steps": [{"step_index": 1, "agent_type": "geometry", "description": "old"}],
            "clarifying_questions": [],
            "unresolved_clarifications": [],
            "answered_clarifications": [],
            "plan_confirmed": True,
        }
    )
    handler = PlanModeHandler(context_manager=ctx, get_agent=lambda *_args, **_kwargs: None)

    with patch.object(PlanModeHandler, "_get_orchestrator") as mock_get:
        mock_get.return_value = SimpleNamespace(run=_fake_orchestrator_run)
        reply, plan, confirmed, _questions = handler.process("改成先建圆柱再传热")

    assert plan is not None
    assert confirmed is False
    assert plan["plan_confirmed"] is False
    assert ctx.load_plan()["plan_confirmed"] is False
