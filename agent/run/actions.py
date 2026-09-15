"""无 Typer 依赖的纯函数：供 TUI 与 CLI 子命令共用的 do_run、do_plan、do_exec 等。"""
import asyncio
import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.case_library import (
    CASE_LIBRARY_TARGET_VERSION,
    get_default_case_library_path,
    list_case_library_items,
    load_case_library,
)
from agent.clawcode_bridge import (
    ensure_default_workflow_manifest,
    ensure_sub_agent_definitions,
    list_workflow_definitions,
    seed_ask_user_runtime,
    worktree_session,
)
from agent.clawcode_bridge.parity import render_parity_report
from agent.doc_knowledge import (
    get_default_doc_kb_path,
    import_comsol_docs,
    load_doc_kb_status,
    search_doc_kb,
)
from agent.core.dependencies import get_agent, get_context_manager, get_settings
from agent.core.events import Event, EventBus, EventType
from agent.executor.comsol_runner import COMSOLRunner
from agent.executor.java_api_controller import JavaAPIController
from agent.memory import update_conversation_memory, update_conversation_memory_async
from agent.agents.qa_agent import QAAgent
from agent.run.discussion_mode import (
    DiscussionModeHandler,
    format_card_brief,
    is_chitchat_only,
)
from agent.utils.env_check import check_environment
from agent.utils.logger import setup_logging, get_logger
from agent.utils.llm import LLMClient
from agent.schemas.geometry import GeometryPlan
from agent.schemas.task import ClarifyingAnswer
from agent.react.exceptions import PlanNeedsClarification, ReActNeedsReorchestrate
from agent.skills import reset_skill_injector
from agent.skills.manager import (
    create_local_skill_library,
    import_skill_library,
    list_local_skill_libraries,
    list_online_skill_library,
)

logger = get_logger(__name__)

_CASE_LIBRARY_SYNC_LOCK = Lock()
_CASE_LIBRARY_SYNC_STATE: Dict[str, Any] = {
    "running": False,
    "status": "idle",
    "message": "",
    "saved_items": 0,
    "total_shallow_records": 0,
}

_DOC_KB_SYNC_LOCK = Lock()
_DOC_KB_SYNC_STATE: Dict[str, Any] = {
    "running": False,
    "status": "idle",
    "message": "",
    "documents": 0,
    "chunks": 0,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _case_library_sync_state_copy() -> Dict[str, Any]:
    with _CASE_LIBRARY_SYNC_LOCK:
        return dict(_CASE_LIBRARY_SYNC_STATE)


def _doc_kb_sync_state_copy() -> Dict[str, Any]:
    with _DOC_KB_SYNC_LOCK:
        return dict(_DOC_KB_SYNC_STATE)

# 与桌面端新会话快捷提示词一致，用于 /demo，与 COMSOL 案例库风格类似：偏 3D、多物理场、包含求解与结果导出。
QUICK_TEST_PROMPTS = [
    # 3D 热-结构（热应力）
    "构建一个 3D 铝合金支架热-结构耦合模型：几何为 0.2 m × 0.1 m × 0.05 m 的带两个圆孔支架，材料采用铝合金（给出 E、nu、density 等）；添加固体传热和固体力学，并通过 Thermal Expansion 建立热应力耦合；底面固定且温度 293.15 K，顶面对流换热（h=10 W/(m^2*K)，环境 293.15 K），一侧面施加恒定热通量 5000 W/m^2；生成适中网格，做稳态研究并求解，最后导出温度场云图和等效应力云图到 output/brace_T3D.png 与 output/brace_sigma3D.png。",
    # 3D 流体-传热（内部冷却）
    "创建一个 3D 管道内部强制对流换热模型：长度 1 m、内径 0.02 m 的圆柱形流道，外部包覆 0.005 m 厚固体壁；流体为水，固体壁为钢或铜；在流体域添加层流流动与流体中的热传导，在固体壁添加固体传热；入口速度 0.5 m/s、温度 293.15 K，出口压力 0 Pa，外壁恒温 353.15 K；生成包含边界层的网格，配置稳态共轭传热研究并求解，导出流体温度场图像到 output/pipe_ctf_T3D.png。",
    # 3D 电磁-传热（线圈发热）
    "构建一个 3D 铜线圈电磁-热耦合模型：若干匝环形铜线圈包围一个钢制工件，外部为空气域；线圈用铜、工件用钢、空气域为空气；在铜线圈和工件区域添加电磁场物理并施加交流电流或电压，使线圈和工件中产生电阻/涡流发热；将电磁发热作为热源耦合到固体传热中，外表面与环境之间采用对流或恒温边界；生成适合 3D 电磁-热问题的网格，做稳态或频域-稳态耦合求解，导出工件温度场云图到 output/coil_heat_T3D.png。",
    # 3D 参数化传热（散热器）
    "构建一个 3D 散热器稳态传热参数化扫描模型：基板 0.1 m × 0.1 m × 0.01 m，上方布置多排散热片（高度约 0.03 m，厚度和间距作为参数）；材料为铝；基板底面施加热通量 10000 W/m^2，上表面与散热片外表面对流换热（h=20 W/(m^2*K)，环境 293.15 K）；添加固体传热，生成适中网格，配置稳态研究并添加参数化扫描（例如按散热片厚度/间距扫描 3~5 个取值）；求解完成后，将每个工况下的最大温度或平均温度导出到 CSV 文件 output/heatsink_parametric.csv。",
]


def _update_memory_after_run(
    conversation_id: Optional[str],
    user_input: str,
    assistant_summary: str,
    success: bool,
) -> None:
    """有 conversation_id 时异步更新会话记忆（本地异步 IO，无 Redis/Celery）。"""
    if not conversation_id:
        return
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(
                update_conversation_memory_async(
                    conversation_id, user_input, assistant_summary, success
                )
            )
        else:
            asyncio.run(
                update_conversation_memory_async(
                    conversation_id, user_input, assistant_summary, success
                )
            )
    except Exception:
        update_conversation_memory(
            conversation_id, user_input, assistant_summary, success
        )


def _emit_stream_text(
    event_bus: Optional[EventBus],
    *,
    phase: str,
    text: str,
    chunk_size: int = 48,
) -> None:
    if event_bus is None:
        return
    content = (text or "").strip()
    if not content:
        return
    for index in range(0, len(content), chunk_size):
        event_bus.emit_type(
            EventType.LLM_STREAM_CHUNK,
            {"phase": phase, "chunk": content[index : index + chunk_size]},
        )


def _summarize_plan_for_history(
    plan_dict: Optional[Dict[str, Any]],
    *,
    plan_confirmed: bool,
    clarifying_questions: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    if not isinstance(plan_dict, dict):
        return {
            "architecture": "plan",
            "plan_confirmed": plan_confirmed,
            "clarifying_questions": len(clarifying_questions or []),
        }

    summary: Dict[str, Any] = {
        "architecture": "plan",
        "plan_confirmed": plan_confirmed,
        "discussion_card_ref": plan_dict.get("discussion_card_ref"),
        "clarifying_questions": len(clarifying_questions or []),
    }
    unresolved = plan_dict.get("unresolved_clarifications")
    if isinstance(unresolved, list):
        summary["unresolved_clarifications"] = unresolved[:10]
    steps = plan_dict.get("steps")
    if isinstance(steps, list):
        slim_steps = []
        for step in steps[:5]:
            if not isinstance(step, dict):
                continue
            slim_steps.append(
                {
                    "step_index": step.get("step_index"),
                    "agent_type": step.get("agent_type"),
                    "description": step.get("description"),
                }
            )
        if slim_steps:
            summary["steps"] = slim_steps
    return summary


def _ensure_logging(verbose: bool = False) -> None:
    setup_logging("DEBUG" if verbose else "INFO")


def _redact(value: Optional[str]) -> str:
    if not value:
        return ""
    return "***"


def _make_dialog_logger(
    context_manager: Any,
    *,
    command: str,
    user_input: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Optional[str],
    Callable[..., None],
    Callable[[bool, str, Optional[Dict[str, Any]]], None],
]:
    log_id: Optional[str] = None
    try:
        started = context_manager.start_dialog_log(
            command=command,
            user_input=user_input,
            metadata=metadata or {},
        )
        log_id = started.get("log_id")
    except Exception as e:
        logger.warning("创建对话动作日志失败: %s", e)

    def log_action(
        action: str,
        detail: str = "",
        *,
        level: str = "INFO",
        source: str = "runtime",
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not log_id:
            return
        try:
            context_manager.append_dialog_action(
                log_id,
                action=action,
                detail=detail,
                level=level,
                source=source,
                data=data,
            )
        except Exception:
            pass

    def finish(success: bool, summary: str, data: Optional[Dict[str, Any]] = None) -> None:
        if not log_id:
            return
        try:
            context_manager.finish_dialog_log(
                log_id,
                success=success,
                summary=summary,
                data=data,
            )
        except Exception:
            pass

    return log_id, log_action, finish


def _attach_event_bus_logger(event_bus: Optional[EventBus], log_action: Callable[..., None]) -> None:
    if event_bus is None:
        return

    def _handler(event: Event) -> None:
        payload: Dict[str, Any] = dict(event.data or {})
        if event.type == EventType.LLM_STREAM_CHUNK:
            chunk = str(payload.get("chunk", ""))
            if len(chunk) > 300:
                payload["chunk"] = chunk[:300] + "...(truncated)"
        log_action(
            f"event:{event.type.value}",
            detail=f"iteration={event.iteration}" if event.iteration is not None else "",
            source="event_bus",
            data={"data": payload, "iteration": event.iteration},
        )

    event_bus.subscribe_all(_handler)


def do_run(
    user_input: str,
    output: Optional[str] = None,
    workspace_dir: Optional[str] = None,
    use_react: bool = True,
    no_context: bool = False,
    conversation_id: Optional[str] = None,
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    ollama_url: Optional[str] = None,
    model: Optional[str] = None,
    max_iterations: int = 10,
    skip_check: bool = False,
    verbose: bool = False,
    event_bus: Optional[EventBus] = None,
    clarifying_answers: Optional[list[dict[str, Any]]] = None,
    given_plan: Optional[Dict[str, Any]] = None,
    use_worktree: bool = False,
    worktree_name: Optional[str] = None,
) -> Tuple[bool, str, bool]:
    """执行默认模式：自然语言 -> 创建模型。given_plan 非空时（Plan 模式进入）直接使用该计划，跳过编排。

    ``use_worktree=True`` 时会通过 ``WorktreeRuntime`` 在仓库旁创建一个 git worktree
    隔离本次建模执行（保留产物，不污染主分支）。worktree 内的 ``.port_sessions/``
    与 ``.context/`` 都独立。
    """
    _ensure_logging(verbose)
    from agent.utils.env_check import validate_environment

    context_manager = get_context_manager(conversation_id)
    _log_id, log_action, finish_log = _make_dialog_logger(
        context_manager,
        command="run",
        user_input=user_input,
        metadata={
            "conversation_id": conversation_id or "default",
            "use_react": use_react,
            "skip_check": skip_check,
            "no_context": no_context,
            "workspace_dir": workspace_dir or "",
            "backend": backend or "",
            "model": model or "",
            "output": output or "",
            "has_api_key": bool(api_key),
            "api_key": _redact(api_key),
            "base_url": base_url or "",
            "ollama_url": ollama_url or "",
            "max_iterations": max_iterations,
            "clarifying_answers_count": len(clarifying_answers or []),
            "has_given_plan": given_plan is not None,
        },
    )
    log_action("run_invoked", data={"input_length": len((user_input or "").strip())})

    if not skip_check:
        log_action("environment_check_started")
        is_valid, error_msg = validate_environment()
        if not is_valid:
            msg = f"环境检查未通过: {error_msg}"
            log_action("environment_check_failed", detail=msg, level="ERROR")
            finish_log(False, msg, {"phase": "validate_environment"})
            return False, msg, False
        log_action("environment_check_passed")
    else:
        log_action("environment_check_skipped")

    # 若本会话已有「已确认」的建模计划，/run 优先沿用；否则不拦截，按自然语言直接走 ReAct（可跳过 discuss/plan）。
    if conversation_id and given_plan is None:
        stored_plan = context_manager.load_plan()
        if stored_plan and bool(stored_plan.get("plan_confirmed")):
            given_plan = stored_plan
            input_rewritten = not bool((user_input or "").strip())
            if input_rewritten:
                user_input = "执行已确认计划"
            log_action(
                "reuse_confirmed_plan",
                data={"plan_confirmed": True, "input_rewritten": input_rewritten},
            )

    memory_context = None if no_context else context_manager.get_context_for_planner()
    log_action(
        "planner_memory_loaded",
        data={
            "has_memory_context": bool((memory_context or "").strip()),
            "memory_context_length": len(memory_context or ""),
        },
    )

    # 可选：用 git worktree 隔离本次建模执行
    worktree_stack = contextlib.ExitStack()
    worktree_report = None
    if use_worktree:
        try:
            from agent.utils.config import get_project_root

            worktree_report = worktree_stack.enter_context(
                worktree_session(
                    get_project_root(), name=worktree_name, cleanup_action="keep"
                )
            )
            if event_bus is not None:
                event_bus.emit_type(
                    EventType.WORKTREE_ENTERED,
                    {
                        "active": worktree_report.active,
                        "session_name": worktree_report.session_name,
                        "worktree_path": worktree_report.worktree_path,
                        "worktree_branch": worktree_report.worktree_branch,
                        "detail": worktree_report.detail,
                    },
                )
            log_action(
                "worktree_entered",
                data={
                    "active": worktree_report.active,
                    "session_name": worktree_report.session_name,
                    "worktree_path": worktree_report.worktree_path,
                },
            )
        except Exception as exc:
            log_action("worktree_enter_failed", detail=str(exc), level="WARNING")
            worktree_report = None

    try:
        if use_react:
            if workspace_dir:
                output_dir = Path(workspace_dir).expanduser().resolve()
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_dir = context_manager.context_dir if conversation_id else None
            if conversation_id:
                context_manager.start_run_log(user_input)
                log_action(
                    "operations_markdown_started",
                    data={"operations_file": str(context_manager.operations_file)},
                )

            active_event_bus = event_bus or EventBus()
            _attach_event_bus_logger(active_event_bus, log_action)
            core = get_agent(
                "core",
                backend=backend,
                api_key=api_key,
                base_url=base_url,
                ollama_url=ollama_url,
                model=model,
                max_iterations=max_iterations,
                event_bus=active_event_bus,
                context_manager=context_manager if conversation_id else None,
            )
            log_action(
                "core_agent_ready",
                data={
                    "event_bus_attached": True,
                    "output_dir": str(output_dir) if output_dir else "",
                },
            )

            # 将前端传来的 clarifying_answers dict 列表转换为 Pydantic 模型列表
            clarifying_models: Optional[list[ClarifyingAnswer]] = None
            if clarifying_answers:
                clarifying_models = []
                for item in clarifying_answers:
                    try:
                        clarifying_models.append(ClarifyingAnswer.model_validate(item))
                    except Exception:
                        continue
            log_action(
                "clarifying_answers_parsed",
                data={
                    "raw_count": len(clarifying_answers or []),
                    "validated_count": len(clarifying_models or []),
                },
            )

            # 把 clarifying_answers 同步到 AskUserRuntime 队列，方便 LocalCodingAgent
            # 在 dispatcher 内部调用 ask_user 工具时复用，并支持离线 .claw-ask-user.json 回放
            if clarifying_models:
                try:
                    from agent.utils.config import get_project_root

                    seed_ask_user_runtime(get_project_root(), clarifying_models)
                    log_action(
                        "ask_user_runtime_seeded",
                        data={"count": len(clarifying_models)},
                    )
                except Exception as exc:  # pragma: no cover
                    log_action(
                        "ask_user_runtime_failed",
                        detail=str(exc),
                        level="WARNING",
                    )

            try:
                model_path = core.run(
                    user_input,
                    output,
                    memory_context=memory_context,
                    output_dir=output_dir,
                    clarifying_answers=clarifying_models,
                    given_plan=given_plan,
                )
                log_action("core_run_finished", data={"model_path": str(model_path)})
            except PlanNeedsClarification as e:
                # 计划已生成但需要澄清问题：视为成功，交由前端展示 PLAN_END 事件与问题列表
                logger.info("Plan 阶段已完成，等待澄清问题回答: %s", e)
                log_action("plan_needs_clarification", detail=str(e))
                context_manager.add_conversation(
                    user_input=user_input,
                    assistant_summary="计划已生成，等待澄清问题回答",
                    plan={"architecture": "react", "status": "plan_needs_clarification"},
                    model_path="",
                    success=True,
                )
                if conversation_id:
                    _update_memory_after_run(
                        conversation_id,
                        user_input,
                        "计划已生成，等待澄清问题回答",
                        True,
                    )
                msg = "计划已生成，等待澄清问题回答"
                finish_log(True, msg, {"phase": "clarification"})
                return True, msg, True

            except ReActNeedsReorchestrate as e:
                # 无效迭代/建议重新编排：调用 PlannerOrchestrator.reorchestrate 并返回用户说明
                from agent.react.iteration_controller import REORCHESTRATE_PREFIX
                from agent.planner.orchestrator import PlannerOrchestrator

                failure_summary = (e.message or "").replace(REORCHESTRATE_PREFIX, "").strip()
                log_action(
                    "react_needs_reorchestrate",
                    detail=failure_summary,
                    level="WARNING",
                )
                orchestrator = PlannerOrchestrator(
                    backend=backend,
                    api_key=api_key,
                    base_url=base_url,
                    ollama_url=ollama_url,
                    model=model,
                )
                try:
                    _task_plan, _ctx, _serial_plan, user_message = orchestrator.reorchestrate(
                        user_input, failure_summary, context=memory_context
                    )
                    log_action("reorchestrate_success")
                except Exception as orch_e:
                    logger.warning("重新编排失败: %s", orch_e)
                    log_action(
                        "reorchestrate_failed",
                        detail=str(orch_e),
                        level="ERROR",
                    )
                    user_message = "执行遇到问题，建议重新编排任务；重新编排调用失败: " + str(orch_e)
                context_manager.add_conversation(
                    user_input=user_input,
                    assistant_summary=user_message,
                    plan={"architecture": "react", "status": "reorchestrate"},
                    model_path="",
                    success=True,
                )
                if conversation_id:
                    _update_memory_after_run(
                        conversation_id,
                        user_input,
                        user_message,
                        True,
                    )
                finish_log(True, user_message, {"phase": "reorchestrate"})
                return True, user_message, True

            context_manager.add_conversation(
                user_input=user_input,
                assistant_summary=f"模型已生成: {model_path}",
                plan={"architecture": "react"},
                model_path=str(model_path),
                success=True,
            )
            if conversation_id:
                _update_memory_after_run(
                    conversation_id,
                    user_input,
                    f"模型已生成: {model_path}",
                    True,
                )
            msg = f"模型已生成: {model_path}"
            finish_log(True, msg, {"model_path": str(model_path), "phase": "run"})
            return True, msg, False
        else:
            context = memory_context
            planner = get_agent(
                "planner",
                backend=backend,
                api_key=api_key,
                base_url=base_url,
                ollama_url=ollama_url,
                model=model,
            )
            plan = planner.parse(user_input, context=context)
            runner = COMSOLRunner()
            model_path = runner.create_model_from_plan(plan, output)
            context_manager.add_conversation(
                user_input=user_input,
                assistant_summary=f"模型已生成: {model_path}",
                plan=plan.to_dict(),
                model_path=str(model_path),
                success=True,
            )
            log_action("planner_direct_run_success", data={"model_path": str(model_path)})
            if conversation_id:
                _update_memory_after_run(
                    conversation_id,
                    user_input,
                    f"模型已生成: {model_path}",
                    True,
                )
            msg = f"模型已生成: {model_path}"
            finish_log(True, msg, {"model_path": str(model_path), "phase": "planner_direct"})
            return True, msg, False
    except Exception as e:
        logger.exception("do_run 失败")
        log_action("run_failed", detail=str(e), level="ERROR", data={"exception_type": type(e).__name__})
        context_manager.add_conversation(
            user_input=user_input,
            assistant_summary=str(e),
            success=False,
            error=str(e),
        )
        if conversation_id:
            _update_memory_after_run(conversation_id, user_input, str(e), False)
        finish_log(False, str(e), {"exception_type": type(e).__name__})
        return False, str(e), False
    finally:
        try:
            worktree_stack.close()
            if worktree_report is not None and event_bus is not None:
                event_bus.emit_type(
                    EventType.WORKTREE_EXITED,
                    {
                        "session_name": worktree_report.session_name,
                        "worktree_path": worktree_report.worktree_path,
                    },
                )
        except Exception as exc:  # pragma: no cover
            log_action("worktree_exit_failed", detail=str(exc), level="WARNING")


def do_workflow(
    workflow_name: Optional[str] = None,
    *,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """暴露 ``WorkflowRuntime`` 的查询能力。

    - 不传 ``workflow_name``：返回所有 workflow 定义（含步骤、metadata）。
    - 传入 ``workflow_name``：返回指定 workflow 的渲染信息。

    实际执行仍走 ``do_run`` / ReActAgent；这里只暴露 manifest 视图，便于
    桌面端展示「mph-agent 标准建模管线」。
    """

    _ensure_logging(verbose)
    try:
        from agent.utils.config import get_project_root

        project_root = get_project_root()
        ensure_default_workflow_manifest(project_root)
        items = list_workflow_definitions(project_root)
        if workflow_name:
            wf = next(
                (item for item in items if item.get("name") == workflow_name),
                None,
            )
            if wf is None:
                return False, f"未找到 workflow: {workflow_name}", {"items": items}
            return True, "ok", {"workflow": wf, "items": items}
        return True, "ok", {"items": items}
    except Exception as exc:
        logger.exception("do_workflow 失败")
        return False, str(exc), {"items": []}


def do_parity(verbose: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    """运行 clawcode parity_audit，并返回 commands/tools 端口清单。"""

    _ensure_logging(verbose)
    try:
        report = render_parity_report(include_backlog=True)
        return True, "ok", report
    except Exception as exc:
        logger.exception("do_parity 失败")
        return False, str(exc), {}


def do_sub_agents_sync(verbose: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    """把 mph-agent 的 planner 子 Agent 写到 ``.claude/agents/*.md``。"""

    _ensure_logging(verbose)
    try:
        from agent.utils.config import get_project_root

        files = ensure_sub_agent_definitions(get_project_root())
        return (
            True,
            f"已写入 {len(files)} 个子 agent 定义",
            {"files": [str(p) for p in files]},
        )
    except Exception as exc:
        logger.exception("do_sub_agents_sync 失败")
        return False, str(exc), {}


def do_plan_mode(
    user_input: str,
    conversation_id: Optional[str] = None,
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    ollama_url: Optional[str] = None,
    model: Optional[str] = None,
    clarifying_answers: Optional[List[Dict[str, Any]]] = None,
    verbose: bool = False,
    event_bus: Optional[EventBus] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]], bool, Optional[List[Dict[str, Any]]]]:
    """
    规划阶段：基于 finalized 讨论卡生成 plan.json + plan_readable.md，并执行澄清闭环。

    Returns:
    - ok
    - reply_text
    - plan_dict
    - plan_confirmed
    - pending_clarifying_questions
    """
    _ensure_logging(verbose)
    context_manager = get_context_manager(conversation_id)
    _log_id, log_action, finish_log = _make_dialog_logger(
        context_manager,
        command="plan",
        user_input=user_input,
        metadata={
            "conversation_id": conversation_id or "default",
            "backend": backend or "",
            "model": model or "",
            "clarifying_answers_count": len(clarifying_answers or []),
        },
    )
    log_action("plan_mode_invoked")
    try:
        if event_bus is not None:
            event_bus.emit_type(EventType.PLAN_START, {"user_input": user_input})
            event_bus.emit_type(EventType.TASK_PHASE, {"phase": "planning"})

        from agent.run.plan_mode import PlanModeHandler

        handler = PlanModeHandler(
            context_manager=context_manager,
            get_agent=get_agent,
            backend=backend,
            api_key=api_key,
            base_url=base_url,
            ollama_url=ollama_url,
            model=model,
        )
        reply, plan_dict, plan_confirmed, clarifying_questions = handler.process(
            user_input,
            clarifying_answers=clarifying_answers,
        )
        if event_bus is not None:
            _emit_stream_text(event_bus, phase="planning", text=reply)
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
                    "plan": plan_dict,
                },
            )

        context_manager.add_conversation(
            user_input=user_input,
            assistant_summary=reply,
            plan=_summarize_plan_for_history(
                plan_dict,
                plan_confirmed=plan_confirmed,
                clarifying_questions=clarifying_questions,
            ),
            success=True,
        )
        if conversation_id:
            _update_memory_after_run(conversation_id, user_input, reply, True)
        log_action(
            "plan_mode_completed",
            data={
                "plan_confirmed": plan_confirmed,
                "has_plan": plan_dict is not None,
                "clarifying_questions": len(clarifying_questions or []),
            },
        )
        finish_log(
            True,
            reply,
            {
                "plan_confirmed": plan_confirmed,
                "clarifying_questions": len(clarifying_questions or []),
            },
        )
        return True, reply, plan_dict, plan_confirmed, clarifying_questions
    except Exception as e:
        logger.exception("do_plan_mode 失败: %s", e)
        log_action("plan_mode_failed", detail=str(e), level="ERROR")
        context_manager.add_conversation(
            user_input=user_input,
            assistant_summary=str(e),
            plan={"architecture": "plan", "status": "error"},
            success=False,
            error=str(e),
        )
        if conversation_id:
            _update_memory_after_run(conversation_id, user_input, str(e), False)
        finish_log(False, str(e), {"exception_type": type(e).__name__})
        return False, str(e), None, False, None


DISCUSS_CHITCHAT_PROMPT = (
    "你是友善、轻松的助手。用户在本软件的 Discuss 模式里，主要想与 LLM 自然闲聊。\n"
    "请用简短、口语化的中文回复，语气亲切，不要像系统通知。\n"
    "可轻描淡写带一句：若要在 COMSOL 里正式建模型，可切换到 Plan（规划）模式描述需求。\n"
    "禁止输出「讨论卡已更新」「原理 N 条」「指标 N 条」等机器统计句式。"
)

DISCUSS_TOPIC_PROMPT = (
    "你是 COMSOL Multiphysics 相关的助手。用户正在 Discuss 模式里梳理建模需求；"
    "系统会在后台维护结构化讨论要点（用户看不到内部字段名）。\n"
    "下面「内部摘要」仅供你参考，请用自然对话回复：回应用户输入，信息不足时温和追问 1～2 个关键点。\n"
    "语气像在讨论方案，不要像打印状态报告。\n"
    "禁止输出「讨论卡已更新」「原理 N 条」等模板句；若合适可提醒：需要进入下一阶段时可发送「进入规划」或切换到规划模式。\n\n"
    "【内部摘要】\n{brief}\n"
)


def _discuss_llm_reply(
    user_text: str,
    *,
    system_prompt: str,
    backend: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    ollama_url: Optional[str],
    model: Optional[str],
    memory_context: str = "",
    event_bus: Optional[EventBus] = None,
) -> str:
    final_system_prompt = system_prompt
    if memory_context.strip():
        final_system_prompt = (
            f"{system_prompt}\n\n"
            f"【会话记忆】\n{memory_context.strip()}\n"
        )
    qa = QAAgent(
        system_prompt=final_system_prompt,
        backend=backend,
        api_key=api_key,
        base_url=base_url,
        ollama_url=ollama_url,
        model=model,
    )
    if event_bus is None:
        return qa.process(user_text)
    return qa.process_stream(
        user_text,
        on_chunk=lambda chunk: event_bus.emit_type(
            EventType.LLM_STREAM_CHUNK,
            {"phase": "discussion", "chunk": chunk},
        ),
    )


def do_discuss(
    user_input: str,
    conversation_id: Optional[str] = None,
    verbose: bool = False,
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    ollama_url: Optional[str] = None,
    model: Optional[str] = None,
    event_bus: Optional[EventBus] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Discuss 阶段：优先 LLM 自然对话；技术性输入仍增量写入 discussion card。"""
    _ensure_logging(verbose)
    context_manager = get_context_manager(conversation_id)
    _log_id, log_action, finish_log = _make_dialog_logger(
        context_manager,
        command="discuss",
        user_input=user_input,
        metadata={
            "conversation_id": conversation_id or "default",
            "backend": backend or "",
            "model": model or "",
            "has_api_key": bool(api_key),
            "api_key": _redact(api_key),
            "base_url": base_url or "",
            "ollama_url": ollama_url or "",
        },
    )
    log_action("discuss_invoked")
    try:
        memory_context = context_manager.get_context_for_planner()
        log_action(
            "discussion_memory_loaded",
            data={
                "has_memory_context": bool(memory_context.strip()),
                "memory_context_length": len(memory_context),
            },
        )
        if event_bus is not None:
            event_bus.emit_type(EventType.TASK_PHASE, {"phase": "discussion"})

        handler = DiscussionModeHandler(context_manager=context_manager)
        resolved = handler.try_resolve_control_messages(user_input)
        if resolved:
            msg, card = resolved
            if event_bus is not None:
                _emit_stream_text(event_bus, phase="discussion", text=msg)
            context_manager.add_conversation(
                user_input=user_input,
                assistant_summary=msg,
                plan={
                    "architecture": "discussion",
                    "mode": "control",
                    "discussion_card_ref": card.get("card_id") if isinstance(card, dict) else None,
                    "discussion_finalized": bool(card.get("finalized")) if isinstance(card, dict) else False,
                },
                success=True,
            )
            if conversation_id:
                _update_memory_after_run(conversation_id, user_input, msg, True)
            log_action("discuss_control_message_resolved")
            finish_log(
                True,
                msg,
                {"control_message": True, "card_finalized": bool(card.get("finalized")) if isinstance(card, dict) else None},
            )
            return True, msg, card

        text = (user_input or "").strip()
        llm_kw = dict(
            backend=backend,
            api_key=api_key,
            base_url=base_url,
            ollama_url=ollama_url,
            model=model,
        )

        if is_chitchat_only(text):
            try:
                reply = _discuss_llm_reply(
                    text,
                    system_prompt=DISCUSS_CHITCHAT_PROMPT,
                    memory_context=memory_context,
                    event_bus=event_bus,
                    **llm_kw,
                )
                log_action("discuss_chitchat_llm_success")
            except Exception as e:
                logger.warning("Discuss 闲聊 LLM 失败，使用兜底: %s", e)
                log_action("discuss_chitchat_llm_failed", detail=str(e), level="WARNING")
                reply = "你好！我在这儿。想聊什么都可以；若要开始整理 COMSOL 建模需求，可以切换到 Plan 模式。"
            card = handler._load_or_create_card()
            context_manager.add_conversation(
                user_input=user_input,
                assistant_summary=reply,
                plan={
                    "architecture": "discussion",
                    "mode": "chitchat",
                    "discussion_card_ref": getattr(card, "card_id", None),
                    "discussion_finalized": bool(getattr(card, "finalized", False)),
                },
                success=True,
            )
            if conversation_id:
                _update_memory_after_run(conversation_id, user_input, reply, True)
            finish_log(
                True,
                reply,
                {
                    "mode": "chitchat",
                    "card_finalized": bool(getattr(card, "finalized", False)),
                },
            )
            return True, reply, card.model_dump(mode="json")

        card = handler._load_or_create_card()
        handler._update_card(card, text)
        handler._save_card(card)
        brief = format_card_brief(card)
        log_action(
            "discussion_card_updated",
            data={
                "physical_principles": len(card.physical_principles),
                "target_metrics": len(card.target_metrics),
                "known_inputs": len(card.known_inputs),
                "unknowns": len(card.unknowns),
                "risks": len(card.risks),
            },
        )
        try:
            reply = _discuss_llm_reply(
                text,
                system_prompt=DISCUSS_TOPIC_PROMPT.format(brief=brief),
                memory_context=memory_context,
                event_bus=event_bus,
                **llm_kw,
            )
            log_action("discuss_topic_llm_success")
        except Exception as e:
            logger.warning("Discuss 技术向 LLM 失败，使用兜底: %s", e)
            log_action("discuss_topic_llm_failed", detail=str(e), level="WARNING")
            reply = (
                "已记下你的描述。若准备生成可执行规划，可发送「进入规划」或切换到规划模式；"
                "也可继续补充几何、材料、边界与目标结果。"
            )
        context_manager.add_conversation(
            user_input=user_input,
            assistant_summary=reply,
            plan={
                "architecture": "discussion",
                "mode": "topic",
                "discussion_card_ref": getattr(card, "card_id", None),
                "discussion_finalized": bool(card.finalized),
                "unknowns": len(card.unknowns),
                "target_metrics": len(card.target_metrics),
            },
            success=True,
        )
        if conversation_id:
            _update_memory_after_run(conversation_id, user_input, reply, True)
        finish_log(
            True,
            reply,
            {
                "mode": "topic",
                "card_finalized": bool(card.finalized),
                "unknowns": len(card.unknowns),
            },
        )
        return True, reply, card.model_dump(mode="json")
    except Exception as e:
        logger.exception("do_discuss 失败")
        log_action("discuss_failed", detail=str(e), level="ERROR")
        context_manager.add_conversation(
            user_input=user_input,
            assistant_summary=str(e),
            plan={"architecture": "discussion", "status": "error"},
            success=False,
            error=str(e),
        )
        if conversation_id:
            _update_memory_after_run(conversation_id, user_input, str(e), False)
        finish_log(False, str(e), {"exception_type": type(e).__name__})
        return False, str(e), None


def do_case(
    model_path: str,
    conversation_id: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[bool, str, Optional[Dict[str, Any]], Optional[str]]:
    """读取 mph 模型并提取结构化操作案例 JSON。"""
    _ensure_logging(verbose)
    context_manager = get_context_manager(conversation_id)
    _log_id, log_action, finish_log = _make_dialog_logger(
        context_manager,
        command="case",
        user_input=model_path,
        metadata={
            "conversation_id": conversation_id or "default",
            "model_path": model_path or "",
        },
    )
    log_action("case_extract_invoked")
    model_path = (model_path or "").strip()
    if not model_path:
        msg = "缺少 model_path"
        log_action("case_extract_failed", detail=msg, level="ERROR")
        finish_log(False, msg)
        return False, msg, None, None
    path = Path(model_path)
    if not path.exists():
        msg = f"模型文件不存在: {model_path}"
        log_action("case_extract_failed", detail=msg, level="ERROR")
        finish_log(False, msg)
        return False, msg, None, None
    if path.suffix.lower() != ".mph":
        msg = "仅支持 .mph 文件"
        log_action("case_extract_failed", detail=msg, level="ERROR")
        finish_log(False, msg)
        return False, msg, None, None
    try:
        ctrl = JavaAPIController()
        result = ctrl.extract_model_operation_case(str(path.resolve()))
        if result.get("status") != "success":
            msg = result.get("message", "案例提取失败")
            log_action("case_extract_failed", detail=msg, level="ERROR")
            finish_log(False, msg)
            return False, msg, None, None

        case_dict = result.get("case")
        if not isinstance(case_dict, dict):
            msg = "案例提取返回格式错误"
            log_action("case_extract_failed", detail=msg, level="ERROR")
            finish_log(False, msg)
            return False, msg, None, None

        saved = context_manager.save_case_file(case_dict, path.stem)
        summary = case_dict.get("summary") or "案例提取完成"
        msg = f"{summary}\n已保存到: {saved}"
        log_action("case_extract_success", data={"saved_path": str(saved)})
        finish_log(True, msg, {"saved_path": str(saved)})
        return True, msg, case_dict, str(saved)
    except Exception as e:
        logger.exception("do_case 失败")
        log_action("case_extract_exception", detail=str(e), level="ERROR")
        finish_log(False, str(e), {"exception_type": type(e).__name__})
        return False, str(e), None, None


def do_case_library_list(
    query: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Return locally indexed official COMSOL case-library items for the desktop UI."""

    _ensure_logging(verbose)
    try:
        items, meta = list_case_library_items(
            query=query,
            category=category,
            limit=limit,
            offset=offset,
        )
        return True, "ok", {
            "items": items,
            "total": meta.get("total", len(items)),
            "limit": meta.get("limit", limit),
            "offset": meta.get("offset", offset),
            "generated_at": meta.get("generated_at"),
            "metadata": meta.get("metadata") or {},
        }
    except Exception as e:
        logger.exception("do_case_library_list 失败")
        return False, str(e), {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "generated_at": None,
            "metadata": {},
        }


def do_case_library_sync_status(verbose: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    """Return current local case-library sync state for the desktop UI."""

    _ensure_logging(verbose)
    state = _case_library_sync_state_copy()
    try:
        output = state.get("output")
        payload = load_case_library(Path(output)) if output else load_case_library()
        state["indexed_items"] = int(payload.get("total") or 0)
        state["generated_at"] = payload.get("generated_at")
        metadata = payload.get("metadata") or {}
        if isinstance(metadata, dict):
            metadata.setdefault("target_version", CASE_LIBRARY_TARGET_VERSION)
            state["metadata"] = metadata
            if not state.get("saved_items"):
                state["saved_items"] = int(metadata.get("saved_items") or 0)
            if not state.get("total_shallow_records"):
                state["total_shallow_records"] = int(metadata.get("total_shallow_records") or 0)
        else:
            state["metadata"] = {}
    except Exception as e:
        logger.exception("do_case_library_sync_status failed")
        state.setdefault("metadata", {})
        state["load_error"] = str(e)
    return True, "ok", state


def do_case_library_sync(
    start_page: int = 1,
    end_page: int = 0,
    limit: int = 0,
    workers: int = 4,
    timeout: float = 20.0,
    delay_ms: int = 100,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Start background crawling for the local COMSOL case-library index."""

    _ensure_logging(verbose)
    output_path = get_default_case_library_path()

    with _CASE_LIBRARY_SYNC_LOCK:
        if _CASE_LIBRARY_SYNC_STATE.get("running"):
            return True, "案例库同步已在进行中", dict(_CASE_LIBRARY_SYNC_STATE)

        _CASE_LIBRARY_SYNC_STATE.clear()
        _CASE_LIBRARY_SYNC_STATE.update(
            {
                "running": True,
                "status": "starting",
                "message": f"正在启动 {CASE_LIBRARY_TARGET_VERSION} 案例库同步...",
                "saved_items": 0,
                "total_shallow_records": 0,
                "indexed_items": 0,
                "started_at": _utc_now_iso(),
                "finished_at": None,
                "output": str(output_path),
                "metadata": {"target_version": CASE_LIBRARY_TARGET_VERSION},
                "last_error": None,
            }
        )

    def progress(payload: Dict[str, Any]) -> None:
        with _CASE_LIBRARY_SYNC_LOCK:
            _CASE_LIBRARY_SYNC_STATE["status"] = str(payload.get("event") or "running")
            if payload.get("message"):
                _CASE_LIBRARY_SYNC_STATE["message"] = str(payload.get("message"))
            if payload.get("saved_items") is not None:
                _CASE_LIBRARY_SYNC_STATE["saved_items"] = int(payload.get("saved_items") or 0)
                _CASE_LIBRARY_SYNC_STATE["indexed_items"] = int(payload.get("saved_items") or 0)
            if payload.get("total_shallow_records") is not None:
                _CASE_LIBRARY_SYNC_STATE["total_shallow_records"] = int(
                    payload.get("total_shallow_records") or 0
                )
            if payload.get("completed") is not None:
                _CASE_LIBRARY_SYNC_STATE["detail_completed"] = int(payload.get("completed") or 0)
            if payload.get("total") is not None:
                _CASE_LIBRARY_SYNC_STATE["detail_total"] = int(payload.get("total") or 0)
            for key in ("page", "title", "official_url", "stage"):
                if payload.get(key) is not None:
                    _CASE_LIBRARY_SYNC_STATE[key] = payload.get(key)
            metadata = _CASE_LIBRARY_SYNC_STATE.setdefault("metadata", {})
            metadata["target_version"] = str(
                payload.get("target_version")
                or metadata.get("target_version")
                or CASE_LIBRARY_TARGET_VERSION
            )

    def worker() -> None:
        try:
            from scripts.sync_comsol_case_library import CrawlConfig, sync_case_library

            config = CrawlConfig(
                start_page=max(1, int(start_page or 1)),
                end_page=max(1, int(end_page)) if end_page else None,
                limit=max(1, int(limit)) if limit else None,
                workers=max(1, int(workers or 4)),
                timeout=max(5.0, float(timeout or 20.0)),
                delay_ms=max(0, int(delay_ms or 0)),
                output=output_path,
                refresh=False,
                progress=progress,
            )
            result = sync_case_library(config)
            payload = load_case_library(output_path)
            with _CASE_LIBRARY_SYNC_LOCK:
                _CASE_LIBRARY_SYNC_STATE.update(
                    {
                        "running": False,
                        "status": "completed",
                        "message": f"{CASE_LIBRARY_TARGET_VERSION} 案例库同步完成",
                        "saved_items": int(result.get("saved_items") or 0),
                        "indexed_items": int(payload.get("total") or 0),
                        "total_shallow_records": int(result.get("total_shallow_records") or 0),
                        "finished_at": _utc_now_iso(),
                        "metadata": payload.get("metadata") or {},
                        "generated_at": payload.get("generated_at"),
                        "last_error": None,
                    }
                )
        except Exception as e:
            logger.exception("do_case_library_sync failed")
            with _CASE_LIBRARY_SYNC_LOCK:
                _CASE_LIBRARY_SYNC_STATE.update(
                    {
                        "running": False,
                        "status": "error",
                        "message": f"{CASE_LIBRARY_TARGET_VERSION} 案例库同步失败: {e}",
                        "finished_at": _utc_now_iso(),
                        "last_error": str(e),
                    }
                )

    Thread(target=worker, name="case-library-sync", daemon=True).start()
    return True, "案例库同步已启动", _case_library_sync_state_copy()


def do_doc_kb_status(verbose: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    """Return current local COMSOL documentation KB state for the desktop UI."""

    _ensure_logging(verbose)
    state = _doc_kb_sync_state_copy()
    try:
        payload = load_doc_kb_status()
        state.update(
            {
                "db_path": payload.get("db_path"),
                "indexed_documents": int(payload.get("documents") or 0),
                "indexed_chunks": int(payload.get("chunks") or 0),
                "generated_at": payload.get("generated_at"),
                "metadata": payload.get("metadata") or {},
            }
        )
        if not state.get("documents"):
            state["documents"] = state["indexed_documents"]
        if not state.get("chunks"):
            state["chunks"] = state["indexed_chunks"]
    except Exception as e:
        logger.exception("do_doc_kb_status failed")
        state.setdefault("metadata", {})
        state["load_error"] = str(e)
    return True, "ok", state


def do_doc_kb_search(
    query: str,
    limit: int = 5,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Search the local COMSOL documentation KB."""

    _ensure_logging(verbose)
    try:
        hits = search_doc_kb(query, limit=max(1, int(limit or 5)))
        return True, "ok", {
            "items": hits,
            "total": len(hits),
            "query": query,
            "limit": max(1, int(limit or 5)),
        }
    except Exception as e:
        logger.exception("do_doc_kb_search failed")
        return False, str(e), {"items": [], "total": 0, "query": query, "limit": limit}


def do_doc_kb_import(
    source_path: str,
    version: str = "6.3",
    limit: int = 0,
    chunk_chars: int = 2400,
    overlap_chars: int = 240,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Start background import for a local COMSOL documentation knowledge base."""

    _ensure_logging(verbose)
    output_path = get_default_doc_kb_path()

    with _DOC_KB_SYNC_LOCK:
        if _DOC_KB_SYNC_STATE.get("running"):
            return True, "文档知识库导入已在进行中", dict(_DOC_KB_SYNC_STATE)

        _DOC_KB_SYNC_STATE.clear()
        _DOC_KB_SYNC_STATE.update(
            {
                "running": True,
                "status": "starting",
                "message": "正在启动 COMSOL 文档知识库导入...",
                "documents": 0,
                "chunks": 0,
                "indexed_documents": 0,
                "indexed_chunks": 0,
                "started_at": _utc_now_iso(),
                "finished_at": None,
                "db_path": str(output_path),
                "source_path": source_path,
                "version": version,
                "metadata": {},
                "last_error": None,
            }
        )

    def progress(payload: Dict[str, Any]) -> None:
        with _DOC_KB_SYNC_LOCK:
            _DOC_KB_SYNC_STATE["status"] = str(payload.get("event") or "running")
            if payload.get("message"):
                _DOC_KB_SYNC_STATE["message"] = str(payload.get("message"))
            if payload.get("documents") is not None:
                _DOC_KB_SYNC_STATE["documents"] = int(payload.get("documents") or 0)
            if payload.get("chunks") is not None:
                _DOC_KB_SYNC_STATE["chunks"] = int(payload.get("chunks") or 0)
            if payload.get("completed") is not None:
                _DOC_KB_SYNC_STATE["completed"] = int(payload.get("completed") or 0)
            if payload.get("total") is not None:
                _DOC_KB_SYNC_STATE["total"] = int(payload.get("total") or 0)
            if payload.get("source_path") is not None:
                _DOC_KB_SYNC_STATE["current_source_path"] = payload.get("source_path")

    def worker() -> None:
        try:
            result = import_comsol_docs(
                source_path=source_path,
                db_path=output_path,
                version=version or "6.3",
                limit=max(1, int(limit)) if limit else None,
                max_chunk_chars=max(400, int(chunk_chars or 2400)),
                overlap_chars=max(0, int(overlap_chars or 0)),
                progress=progress,
            )
            payload = load_doc_kb_status(output_path)
            reset_skill_injector()
            with _DOC_KB_SYNC_LOCK:
                _DOC_KB_SYNC_STATE.update(
                    {
                        "running": False,
                        "status": "completed",
                        "message": "COMSOL 文档知识库导入完成",
                        "documents": int(result.get("documents") or 0),
                        "chunks": int(result.get("chunks") or 0),
                        "indexed_documents": int(payload.get("documents") or 0),
                        "indexed_chunks": int(payload.get("chunks") or 0),
                        "finished_at": _utc_now_iso(),
                        "generated_at": payload.get("generated_at"),
                        "metadata": payload.get("metadata") or {},
                        "last_error": None,
                    }
                )
        except Exception as e:
            logger.exception("do_doc_kb_import failed")
            with _DOC_KB_SYNC_LOCK:
                _DOC_KB_SYNC_STATE.update(
                    {
                        "running": False,
                        "status": "error",
                        "message": f"COMSOL 文档知识库导入失败: {e}",
                        "finished_at": _utc_now_iso(),
                        "last_error": str(e),
                    }
                )

    Thread(target=worker, name="doc-kb-import", daemon=True).start()
    return True, "COMSOL 文档知识库导入已启动", _doc_kb_sync_state_copy()


def do_skills_list_local(verbose: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    """Return repo-local skill libraries for the desktop UI."""

    _ensure_logging(verbose)
    try:
        items = list_local_skill_libraries()
        return True, "ok", {"items": items, "total": len(items)}
    except Exception as e:
        logger.exception("do_skills_list_local failed")
        return False, str(e), {"items": [], "total": 0}


def do_skills_create_local(
    name: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    triggers: Optional[List[str]] = None,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Create a new repo-local skill library."""

    _ensure_logging(verbose)
    try:
        result = create_local_skill_library(
            name=name,
            description=description,
            tags=tags or [],
            triggers=triggers or [],
        )
        reset_skill_injector()
        return True, "技能库已创建", result
    except Exception as e:
        logger.exception("do_skills_create_local failed")
        return False, str(e), {"item": None}


def do_skills_import_local(
    source_path: str,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Import an existing skill directory or SKILL.md into the repo-local skill library."""

    _ensure_logging(verbose)
    try:
        result = import_skill_library(source_path)
        reset_skill_injector()
        return True, "技能库已导入", result
    except Exception as e:
        logger.exception("do_skills_import_local failed")
        return False, str(e), {"item": None}


def do_skills_list_online(verbose: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    """Return a curated read-only online skill catalog."""

    _ensure_logging(verbose)
    try:
        items = list_online_skill_library()
        return True, "ok", {"items": items, "total": len(items)}
    except Exception as e:
        logger.exception("do_skills_list_online failed")
        return False, str(e), {"items": [], "total": 0}


def do_ops_catalog(
    query: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    *,
    wrappers_only: bool = False,
    verbose: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """返回 COMSOL 操作能力目录（默认可含 native + wrapper；wrappers_only 时仅官方 API 包装条目）。"""
    _ensure_logging(verbose)
    try:
        ctrl = JavaAPIController()
        result = ctrl.get_ops_catalog(
            query=query, limit=limit, offset=offset, wrappers_only=wrappers_only
        )
        ok = result.get("status") == "success"
        message = result.get("message", "ok" if ok else "error")
        return ok, str(message), result
    except Exception as e:
        logger.exception("do_ops_catalog 失败")
        return False, str(e), {
            "status": "error",
            "message": str(e),
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }


def do_plan(
    user_input: str,
    output_path: Optional[Path] = None,
    verbose: bool = False,
) -> Tuple[bool, str]:
    """计划模式：自然语言 -> JSON。返回 (成功, 要显示的文本)。"""
    _ensure_logging(verbose)
    try:
        planner = get_agent("planner")
        plan = planner.parse(user_input)
        plan_dict = plan.to_dict()
        text = json.dumps(plan_dict, ensure_ascii=False, indent=2)
        if output_path:
            output_path.write_text(text, encoding="utf-8")
            return True, f"计划已保存到: {output_path}\n\n{text}"
        return True, text
    except Exception as e:
        logger.exception("do_plan 失败")
        return False, str(e)


def do_exec_from_file(
    plan_file: Path,
    output: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[bool, str]:
    """根据 JSON 计划文件执行：创建模型。"""
    _ensure_logging(verbose)
    try:
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
        plan = GeometryPlan.from_dict(plan_data)
        runner = COMSOLRunner()
        model_path = runner.create_model_from_plan(plan, output)
        return True, f"模型已生成: {model_path}"
    except Exception as e:
        logger.exception("do_exec 失败")
        return False, str(e)


def do_demo(verbose: bool = False) -> Tuple[bool, str]:
    """运行演示用例（与桌面端快捷提示词一致，覆盖仅几何、材料、物理场、研究、完整流程），返回汇总文本。"""
    _ensure_logging(verbose)
    lines = ["Multiphysics Modeling Agent 演示（测试各链路）\n"]
    planner = get_agent("planner")
    for i, case in enumerate(QUICK_TEST_PROMPTS, 1):
        lines.append(f"示例 {i}: {case}")
        try:
            plan = planner.parse(case)
            shapes = getattr(plan, "shapes", None)
            if shapes is not None:
                lines.append(f"  解析成功: {len(shapes)} 个形状, 模型名: {getattr(plan, 'model_name', 'model')}, 单位: {getattr(plan, 'units', 'm')}")
            else:
                # 编排器返回 TaskPlan，可能含 geometry/material/physics/study
                geom = getattr(plan, "geometry", None)
                n_shapes = len(getattr(geom, "shapes", [])) if geom else 0
                lines.append(f"  解析成功: 几何 {n_shapes} 个形状, 含 material={getattr(plan, 'material', None) is not None}, physics={getattr(plan, 'physics', None) is not None}, study={getattr(plan, 'study', None) is not None}")
        except Exception as e:
            lines.append(f"  解析失败: {e}")
        lines.append("")
    return True, "\n".join(lines)


def do_doctor(verbose: bool = False) -> Tuple[bool, str]:
    """运行环境诊断，返回结果文本。"""
    _ensure_logging(verbose)
    settings = get_settings()
    status = settings.show_config_status()
    result = check_environment()
    lines = [f"各后端配置状态: {status}", ""]
    lines.append(
        "内置 claw-code: "
        + ("已启用" if getattr(settings, "claw_code_enabled", False) else "已禁用")
        + f"，模型: {settings.claw_code_model or settings.get_model_for_backend(settings.llm_backend)}"
    )
    lines.append("")
    try:
        report = render_parity_report(include_backlog=True)
        lines.append("clawcode parity 概览:")
        lines.append(
            "- 文件覆盖: {}/{}; 命令端口: {}/{}; 工具端口: {}/{}".format(
                *report.get("total_file_ratio", (0, 0)),
                *report.get("command_entry_ratio", (0, 0)),
                *report.get("tool_entry_ratio", (0, 0)),
            )
        )
        if report.get("missing_directory_targets"):
            lines.append(
                "- 待补齐目录: " + ", ".join(report["missing_directory_targets"][:6])
            )
        commands_block = report.get("commands") or {}
        tools_block = report.get("tools") or {}
        lines.append(
            f"- 已 ported 命令数: {commands_block.get('ported_count', 0)}; "
            f"工具数: {tools_block.get('ported_count', 0)}"
        )
        lines.append("")
    except Exception as exc:
        lines.append(f"clawcode parity 报告失败: {exc}")
        lines.append("")
    if result.is_valid():
        lines.append("环境检查通过")
    else:
        lines.append("环境检查失败")
    for e in result.errors:
        lines.append(f"  错误: {e}")
    for w in result.warnings:
        lines.append(f"  警告: {w}")
    for i in result.info:
        lines.append(f"  {i}")
    return result.is_valid(), "\n".join(lines)


def do_context_show(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """上下文摘要。conversation_id 存在时查看该会话的摘要。"""
    cm = get_context_manager(conversation_id)
    summary = cm.load_summary()
    if summary:
        return True, f"{summary.summary}\n\n最后更新: {summary.last_updated[:19]}"
    return True, "暂无上下文摘要"


def do_context_get_summary(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """仅返回当前会话的摘要原文（供设置页编辑）。"""
    cm = get_context_manager(conversation_id)
    return True, cm.get_editable_summary_text()


def do_context_prompt_context(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """Return the prompt-side memory/context block for usage estimation."""
    cm = get_context_manager(conversation_id)
    return True, cm.get_context_for_planner()


def do_context_set_summary(conversation_id: Optional[str], text: str) -> Tuple[bool, str]:
    """设置当前会话的摘要原文（用户编辑记忆）。"""
    if not conversation_id:
        return False, "缺少 conversation_id"
    cm = get_context_manager(conversation_id)
    cm.set_summary_text(text)
    return True, "记忆已保存"


def do_ollama_ping(ollama_url: str) -> Tuple[bool, str]:
    """测试 Ollama 服务连通性。"""
    url = (ollama_url or "").strip()
    if not url:
        return False, "请填写 Ollama 地址"
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    try:
        import requests
        r = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        if r.status_code == 200:
            models = r.json().get("models", [])
            names = [m.get("name", "") for m in models[:5]]
            return True, f"连接成功，可用模型: {', '.join(names) or '无'}"
        return False, f"响应异常: HTTP {r.status_code}"
    except Exception as e:
        return False, f"连接失败: {e}"


def do_context_history(limit: int = 10, conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """对话历史。"""
    cm = get_context_manager(conversation_id)
    history_list = cm.get_recent_history(limit)
    lines = [f"最近 {len(history_list)} 条对话历史\n"]
    for i, entry in enumerate(history_list, 1):
        ts = entry.get("timestamp", "")[:19]
        ui = (entry.get("user_input") or "")[:60]
        ok = entry.get("success", True)
        st = "成功" if ok else "失败"
        lines.append(f"{i}. [{st}] {ts} {ui}...")
    return True, "\n".join(lines)


def do_context_stats(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """上下文统计。"""
    cm = get_context_manager(conversation_id)
    data = cm.get_stats()
    lines = [
        f"总对话数: {data['total_conversations']}",
        f"成功: {data['successful']}",
        f"失败: {data['failed']}",
    ]
    if data.get("recent_shapes"):
        lines.append(f"最近形状: {', '.join(data['recent_shapes'])}")
    if data.get("preferences"):
        lines.append(f"用户偏好: {data['preferences']}")
    return True, "\n".join(lines)


def do_context_clear(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """清除对话历史。"""
    get_context_manager(conversation_id).clear_history()
    return True, "对话历史已清除"


def do_config_save(env_updates: Optional[dict] = None) -> Tuple[bool, str]:
    """将配置写入项目根目录的 .env 文件并重载配置，供桌面端保存后同步。"""
    if not env_updates:
        return False, "无配置项"
    from agent.utils.config import get_project_root, reload_settings

    root = get_project_root()
    env_path = root / ".env"
    env_keys = [
        "LLM_BACKEND",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "KIMI_API_KEY",
        "KIMI_MODEL",
        "OPENAI_COMPATIBLE_API_KEY",
        "OPENAI_COMPATIBLE_BASE_URL",
        "OPENAI_COMPATIBLE_MODEL",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "COMSOL_JAR_PATH",
        "JAVA_HOME",
        "MODEL_OUTPUT_DIR",
        "CLAW_CODE_ENABLED",
        "CLAW_CODE_MAX_TURNS",
        "CLAW_CODE_TIMEOUT_SECONDS",
        "CLAW_CODE_MODEL",
        "CLAW_CODE_BASE_URL",
        "CLAW_CODE_API_KEY",
    ]
    env_updates = _with_claw_code_llm_defaults(dict(env_updates))
    # 读取已有行
    if env_path.exists():
        lines_out = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines_out = []
    # 键 -> 行索引（只记第一个出现的键）
    key_to_idx: dict[str, int] = {}
    for i, line in enumerate(lines_out):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            key = s.split("=", 1)[0].strip()
            if key not in key_to_idx:
                key_to_idx[key] = i
    # 更新或追加
    for k in env_keys:
        v = env_updates.get(k)
        if v is None:
            continue
        v_str = str(v).strip()
        new_line = f"{k}={v_str}"
        if k in key_to_idx:
            lines_out[key_to_idx[k]] = new_line
        else:
            lines_out.append(new_line)
            key_to_idx[k] = len(lines_out) - 1
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
        reload_settings()
        return True, "配置已保存并已加载，将应用于后续 mph-agent 调用"
    except Exception as e:
        return False, f"写入 .env 失败: {e}"


def _with_claw_code_llm_defaults(env_updates: dict) -> dict:
    """Align opt-in claw-code LLM keys with the selected desktop backend.

    Does not write or override ``CLAW_CODE_ENABLED``; modeling defaults to local Java API.
    """

    backend = str(env_updates.get("LLM_BACKEND") or "").strip()
    if not backend:
        return env_updates

    if backend == "deepseek":
        env_updates.setdefault("CLAW_CODE_MODEL", env_updates.get("DEEPSEEK_MODEL", ""))
        env_updates.setdefault("CLAW_CODE_BASE_URL", "https://api.deepseek.com/v1")
        env_updates.setdefault("CLAW_CODE_API_KEY", env_updates.get("DEEPSEEK_API_KEY", ""))
    elif backend == "kimi":
        env_updates.setdefault("CLAW_CODE_MODEL", env_updates.get("KIMI_MODEL", ""))
        env_updates.setdefault("CLAW_CODE_BASE_URL", "https://api.moonshot.cn/v1")
        env_updates.setdefault("CLAW_CODE_API_KEY", env_updates.get("KIMI_API_KEY", ""))
    elif backend == "openai-compatible":
        env_updates.setdefault("CLAW_CODE_MODEL", env_updates.get("OPENAI_COMPATIBLE_MODEL", ""))
        env_updates.setdefault(
            "CLAW_CODE_BASE_URL", env_updates.get("OPENAI_COMPATIBLE_BASE_URL", "")
        )
        env_updates.setdefault("CLAW_CODE_API_KEY", env_updates.get("OPENAI_COMPATIBLE_API_KEY", ""))
    elif backend == "ollama":
        ollama_url = str(env_updates.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        env_updates.setdefault("CLAW_CODE_MODEL", env_updates.get("OLLAMA_MODEL", ""))
        env_updates.setdefault("CLAW_CODE_BASE_URL", f"{ollama_url}/v1")
        env_updates.setdefault("CLAW_CODE_API_KEY", "local-token")
    return env_updates


def do_conversation_title_suggest(
    user_input: str,
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    ollama_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[bool, str]:
    """根据首条用户输入生成会话标题。"""
    text = (user_input or "").strip()
    if not text:
        return False, "输入为空"
    try:
        settings = get_settings()
        resolved_backend = backend or settings.llm_backend
        llm = LLMClient(
            backend=resolved_backend,
            api_key=api_key or settings.get_api_key_for_backend(resolved_backend),
            base_url=base_url or settings.get_base_url_for_backend(resolved_backend),
            ollama_url=ollama_url or settings.ollama_url,
            model=model or settings.get_model_for_backend(resolved_backend),
        )
        prompt = (
            "请将以下建模需求总结成一个中文会话标题。"
            "要求：8-20字、聚焦任务主题、不加引号、不加句号。\n\n"
            f"需求：{text}\n\n标题："
        )
        title = (llm.call(prompt, temperature=0.2) or "").strip().strip("“”\"' \n\r\t")
        if not title:
            raise ValueError("empty title")
        if len(title) > 30:
            title = title[:30].rstrip("，,。.；;:：")
        return True, title
    except Exception as e:
        logger.warning("会话标题生成失败，使用兜底: %s", e)
        fallback = text[:18].strip()
        if len(text) > 18:
            fallback += "..."
        return True, fallback or "新会话"


def do_list_apis(
    query: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> Tuple[bool, str]:
    """
    列出已集成的 COMSOL 官方 Java API 包装函数。
    返回 JSON 文本，包含 items/total/limit/offset 等字段。
    """
    try:
        ctrl = JavaAPIController()
        result = ctrl.list_official_api_wrappers(query=query, limit=limit, offset=offset)
        if result.get("status") != "success":
            return False, result.get("message", "list_official_api_wrappers 调用失败")
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return True, text
    except Exception as e:
        logger.exception("do_list_apis 失败")
        return False, str(e)
