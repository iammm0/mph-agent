"""Tests for unified chat pipeline (discuss -> plan -> run)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from agent.run.chat_pipeline import run_chat_pipeline
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
        return True

    def get_context_for_planner(self) -> str:
        return ""


def _fake_orchestrator_run(discuss_text, context=""):
    task_plan = SimpleNamespace(
        model_dump=lambda: {"goal": (discuss_text or "")[:80], "steps": []}
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


def test_chat_pipeline_chitchat_skips_plan_and_run():
    ctx = _DummyContextManager()
    discuss_calls: List[str] = []
    run_calls: List[str] = []

    def fake_discuss(**kwargs):
        discuss_calls.append(kwargs.get("user_input") or "")
        return True, "嗨，你好呀", {"finalized": False}

    def fake_run(**kwargs):
        run_calls.append(kwargs.get("user_input") or "")
        return True, "should not run", False

    ok, msg, plan, confirmed, questions, executed = run_chat_pipeline(
        user_input="你好",
        context_manager=ctx,
        do_discuss_fn=fake_discuss,
        do_run_fn=fake_run,
        get_agent=lambda *a, **k: None,
    )

    assert ok is True
    assert executed is False
    assert plan is None
    assert confirmed is False
    assert questions is None
    assert discuss_calls == ["你好"]
    assert run_calls == []
    assert "你好" in msg or "嗨" in msg


def test_chat_pipeline_pauses_on_clarification_without_run():
    ctx = _DummyContextManager()
    ctx.save_discussion_card(
        DiscussionCard(
            finalized=True,
            physical_principles=["热传导"],
            unknowns=["对流系数未知"],
        ).model_dump(mode="json")
    )
    run_calls: List[str] = []

    def fake_run(**kwargs):
        run_calls.append("called")
        return True, "ran", False

    with patch.object(PlanModeHandler, "_get_orchestrator") as mock_get:
        mock_get.return_value = SimpleNamespace(run=_fake_orchestrator_run)
        ok, reply, plan, confirmed, questions, executed = run_chat_pipeline(
            user_input="做一个传热模型",
            context_manager=ctx,
            do_discuss_fn=lambda **k: (True, "unused", {}),
            do_run_fn=fake_run,
            get_agent=lambda *a, **k: None,
        )

    assert ok is True
    assert executed is False
    assert confirmed is False
    assert plan is not None
    assert isinstance(questions, list) and len(questions) >= 1
    assert run_calls == []
    assert "澄清" in reply


def test_chat_pipeline_auto_confirms_and_runs_when_no_questions():
    ctx = _DummyContextManager()
    ctx.save_discussion_card(
        DiscussionCard(
            finalized=True,
            physical_principles=["几何"],
            known_inputs=["边长 1m"],
        ).model_dump(mode="json")
    )
    run_plans: List[Optional[Dict[str, Any]]] = []

    def fake_run(**kwargs):
        run_plans.append(kwargs.get("given_plan"))
        return True, "建模完成", False

    with patch.object(PlanModeHandler, "_get_orchestrator") as mock_get:
        mock_get.return_value = SimpleNamespace(run=_fake_orchestrator_run)
        ok, reply, plan, confirmed, questions, executed = run_chat_pipeline(
            user_input="创建一个矩形",
            context_manager=ctx,
            do_discuss_fn=lambda **k: (True, "unused", {}),
            do_run_fn=fake_run,
            get_agent=lambda *a, **k: None,
        )

    assert ok is True
    assert executed is True
    assert confirmed is True
    assert questions is None
    assert plan is not None
    assert plan["plan_confirmed"] is True
    assert run_plans and run_plans[0] is not None
    assert "建模完成" in reply


def test_chat_pipeline_clarifying_answers_resume_to_run():
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
            "steps": [],
        }
    )
    run_called = {"n": 0}

    def fake_run(**kwargs):
        run_called["n"] += 1
        return True, "继续执行完成", False

    ok, reply, plan, confirmed, questions, executed = run_chat_pipeline(
        user_input="确认",
        context_manager=ctx,
        do_discuss_fn=lambda **k: (True, "unused", {}),
        do_run_fn=fake_run,
        get_agent=lambda *a, **k: None,
        clarifying_answers=[
            {"question_id": "q1", "selected_option_ids": ["opt_recommended"]}
        ],
    )

    assert ok is True
    assert executed is True
    assert confirmed is True
    assert questions is None
    assert plan is not None
    assert plan["plan_confirmed"] is True
    assert run_called["n"] == 1
    assert "继续执行完成" in reply
