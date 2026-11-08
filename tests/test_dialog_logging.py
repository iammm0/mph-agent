"""Tests for per-dialog action logs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from agent.core.events import EventBus, EventType
from agent.run import actions
from agent.utils.context_manager import ContextManager


def test_context_manager_dialog_log_roundtrip(tmp_path):
    cm = ContextManager(context_dir=tmp_path / "ctx")
    started = cm.start_dialog_log(
        command="run",
        user_input="创建测试模型",
        metadata={"conversation_id": "c1"},
    )
    log_id = started["log_id"]
    md_path = Path(started["markdown_path"])
    jsonl_path = Path(started["jsonl_path"])

    cm.append_dialog_action(
        log_id,
        action="phase:start",
        detail="开始执行",
        data={"step": 1},
    )
    cm.finish_dialog_log(log_id, success=True, summary="完成", data={"ok": True})

    assert md_path.exists()
    assert jsonl_path.exists()

    md = md_path.read_text(encoding="utf-8")
    assert "命令: `run`" in md
    assert "phase:start" in md
    assert "状态: `SUCCESS`" in md

    lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line]
    events = [item.get("event") for item in lines]
    assert events[0] == "dialog_start"
    assert "action" in events
    assert events[-1] == "dialog_end"


def test_do_run_creates_dialog_log_and_records_events(tmp_path, monkeypatch):
    cm = ContextManager(context_dir=tmp_path / "ctx")
    model_path = tmp_path / "demo_model.mph"
    model_path.write_text("dummy", encoding="utf-8")

    class _FakeCore:
        def __init__(self, bus: Optional[EventBus]) -> None:
            self._bus = bus

        def run(self, user_input: str, *_args: Any, **_kwargs: Any) -> Path:
            if self._bus:
                self._bus.emit_type(EventType.PLAN_START, {"user_input": user_input})
                self._bus.emit_type(EventType.STEP_START, {"step_type": "几何建模"})
                self._bus.emit_type(
                    EventType.RUN_END,
                    {"success": True, "model_path": str(model_path)},
                )
            return model_path

    def _fake_get_agent(agent_type: str, **kwargs: Dict[str, Any]):
        if agent_type == "core":
            return _FakeCore(kwargs.get("event_bus"))
        raise AssertionError(f"unexpected agent_type: {agent_type}")

    monkeypatch.setattr(actions, "get_context_manager", lambda *_args, **_kwargs: cm)
    monkeypatch.setattr(actions, "get_agent", _fake_get_agent)
    monkeypatch.setattr(actions, "_update_memory_after_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("agent.utils.env_check.validate_environment", lambda: (True, ""))

    ok, message, need_clarify = actions.do_run(
        user_input="创建一个简单模型",
        conversation_id="conv-1",
        use_react=True,
        skip_check=False,
    )

    assert ok is True
    assert need_clarify is False
    # do_run 成功文案随是否求解而变：求解成功 / 模型已生成
    assert ("求解成功" in message) or ("模型已生成" in message)

    log_files = sorted((cm.context_dir / "dialog_logs").glob("*.md"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "命令: `run`" in content
    assert "event:plan_start" in content
    assert "event:step_start" in content
    assert "event:run_end" in content
    assert "状态: `SUCCESS`" in content
