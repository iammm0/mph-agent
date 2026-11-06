"""Unified chat pipeline: discuss -> plan (pause on clarification) -> run."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from agent.core.events import EventBus, EventType
from agent.run.discussion_mode import DiscussionModeHandler, is_chitchat_only
from agent.run.plan_mode import PlanModeHandler
from agent.utils.logger import get_logger

logger = get_logger(__name__)


def run_chat_pipeline(
    *,
    user_input: str,
    context_manager: Any,
    do_discuss_fn: Any,
    do_run_fn: Any,
    get_agent: Any,
    conversation_id: Optional[str] = None,
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    ollama_url: Optional[str] = None,
    model: Optional[str] = None,
    output: Optional[str] = None,
    workspace_dir: Optional[str] = None,
    skip_check: bool = False,
    verbose: bool = False,
    clarifying_answers: Optional[List[Dict[str, Any]]] = None,
    event_bus: Optional[EventBus] = None,
) -> Tuple[
    bool,
    str,
    Optional[Dict[str, Any]],
    bool,
    Optional[List[Dict[str, Any]]],
    bool,
]:
    """
    Returns:
    - ok
    - reply_text
    - plan_dict (if any)
    - plan_confirmed
    - clarifying_questions (when paused)
    - executed_run
    """
    text = (user_input or "").strip()
    answers = clarifying_answers or None

    llm_kw = dict(
        backend=backend,
        api_key=api_key,
        base_url=base_url,
        ollama_url=ollama_url,
        model=model,
    )

    # Clarification resume: skip discuss rewrite, continue plan -> run.
    if not answers and is_chitchat_only(text):
        if event_bus is not None:
            event_bus.emit_type(EventType.TASK_PHASE, {"phase": "discussion"})
        ok, msg, _card = do_discuss_fn(
            user_input=text,
            conversation_id=conversation_id,
            verbose=verbose,
            event_bus=event_bus,
            **llm_kw,
        )
        return ok, msg, None, False, None, False

    if not answers:
        if event_bus is not None:
            event_bus.emit_type(EventType.TASK_PHASE, {"phase": "discussion"})
        handler = DiscussionModeHandler(context_manager=context_manager)
        # Ignore control-only keywords; treat as normal modeling text when empty points.
        card = handler._load_or_create_card()
        card.finalized = False
        changed = handler._update_card(card, text) if text else False
        # Soft-finalize so plan can use the card; pipeline owns confirmation.
        if changed or text:
            card.finalized = True
            handler._save_card(card)
            if changed:
                handler._invalidate_plan_if_needed()
        else:
            handler._save_card(card)

    if event_bus is not None:
        event_bus.emit_type(EventType.TASK_PHASE, {"phase": "planning"})
        event_bus.emit_type(EventType.PLAN_START, {"user_input": text})

    plan_handler = PlanModeHandler(
        context_manager=context_manager,
        get_agent=get_agent,
        **llm_kw,
    )
    plan_input = text or "继续建模流水线"
    reply, plan_dict, plan_confirmed, clarifying_questions = plan_handler.process(
        plan_input,
        clarifying_answers=answers,
        auto_confirm=True,
    )

    if event_bus is not None:
        event_bus.emit_type(
            EventType.PLAN_END,
            {
                "plan_confirmed": plan_confirmed,
                "clarifying_questions": clarifying_questions or [],
                "unresolved_clarifications": (
                    plan_dict.get("unresolved_clarifications", [])
                    if isinstance(plan_dict, dict)
                    else []
                ),
                "requires_clarification": bool(clarifying_questions),
                "plan": plan_dict,
            },
        )

    if clarifying_questions:
        if event_bus is not None and reply:
            content = reply.strip()
            for index in range(0, len(content), 48):
                event_bus.emit_type(
                    EventType.LLM_STREAM_CHUNK,
                    {"phase": "planning", "chunk": content[index : index + 48]},
                )
        return True, reply, plan_dict, False, clarifying_questions, False

    if not plan_confirmed or not isinstance(plan_dict, dict):
        return True, reply, plan_dict, False, None, False

    if event_bus is not None:
        event_bus.emit_type(EventType.TASK_PHASE, {"phase": "running"})

    ok, run_msg, _needs_clarification = do_run_fn(
        user_input=text or "执行已确认计划",
        output=output,
        workspace_dir=workspace_dir,
        use_react=True,
        no_context=False,
        conversation_id=conversation_id,
        skip_check=skip_check,
        verbose=verbose,
        event_bus=event_bus,
        given_plan=plan_dict,
        **llm_kw,
    )
    combined = reply
    if run_msg:
        combined = f"{reply}\n\n{run_msg}" if reply else run_msg
    return ok, combined, plan_dict, True, None, True
