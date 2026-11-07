"""ReAct Agent 核心类"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, cast
from uuid import uuid4

from agent.core.events import EventBus, EventType
from agent.react.action_executor import ActionExecutor
from agent.react.error_collector import ErrorCollector
from agent.react.exceptions import PlanNeedsClarification, ReActNeedsReorchestrate
from agent.react.iteration_controller import IterationController, REORCHESTRATE_PREFIX
from agent.react.observer import Observer
from agent.react.reasoning_engine import ReasoningEngine
from agent.utils.config import get_project_root, get_settings
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.schemas.task import ClarifyingAnswer, ExecutionStep, Observation, ReActTaskPlan

logger = get_logger(__name__)

_STEP_LABELS = {
    "create_geometry": "几何建模",
    "define_globals": "全局参数",
    "add_material": "材料设置",
    "update_material_property": "材料属性修补",
    "add_physics": "物理场与边界",
    "generate_mesh": "网格划分",
    "configure_study": "研究配置",
    "solve": "求解",
    "export_results": "结果导出",
    "evaluate_results": "结果求值",
    "set_parameters": "参数设置",
    "import_geometry": "导入几何",
    "create_selection": "创建选择集",
    "call_official_api": "官方 API 细控",
}

_STEP_WHY = {
    "create_geometry": "几何是材料、物理场与网格的载体，必须先闭环几何。",
    "define_globals": "把尺寸/载荷等写成全局参数，便于后续复现与调参。",
    "add_material": "物理场求解依赖完整材料属性（如 E/nu/k），缺属性无法可算。",
    "update_material_property": "在已有材料上补齐缺失属性，避免整树重建。",
    "add_physics": "定义控制方程与边界/载荷，决定模型是否可求解。",
    "generate_mesh": "离散化几何是数值求解的前提。",
    "configure_study": "选择稳态/瞬态等研究类型并装配求解器。",
    "solve": "执行求解以验证模型可计算，这是闭环的最终目标。",
    "export_results": "把可交付结果图/数据落盘，便于验收。",
    "evaluate_results": "对已求解模型求值（优先 MPh），用于温度/位移等标量验收。",
    "set_parameters": "批量改全局参数（优先 MPh），用于参数化扫描改参。",
    "import_geometry": "复用外部 CAD/几何文件以缩短建模路径。",
    "create_selection": "为边界/域操作建立可引用选择集。",
    "call_official_api": "用官方 Java API 做细粒度节点控制。",
}


def _param_highlights(parameters: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(parameters, dict):
        return []
    keys = (
        "geometry_input",
        "material_input",
        "physics_input",
        "study_input",
        "mesh",
        "file_path",
        "out_path",
        "wrapper",
        "wrapper_name",
        "method",
    )
    out: List[str] = []
    for key in keys:
        val = parameters.get(key)
        if val is None or val == "" or val == {}:
            continue
        if isinstance(val, (dict, list)):
            text = str(val)
        else:
            text = str(val).strip()
        if not text:
            continue
        if len(text) > 220:
            text = text[:217] + "..."
        out.append(f"{key}: {text}")
    return out


def _serialize_modeling_steps(plan: ReActTaskPlan) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for idx, step in enumerate(plan.execution_path, start=1):
        params = step.parameters or {}
        steps.append(
            {
                "index": idx,
                "action": step.action,
                "step_type": step.step_type,
                "label": _STEP_LABELS.get(step.action, step.action),
                "why": _STEP_WHY.get(step.action, "按 COMSOL 建模流程推进，服务最终可求解闭环。"),
                "inputs": _param_highlights(params),
                "parameters": params,
                "status": step.status,
            }
        )
    return steps


class ReActAgent:
    """ReAct Agent - 协调推理和执行；可选 EventBus 用于可观测。"""

    def __init__(
        self,
        llm: Optional[Any] = None,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
        max_iterations: Optional[int] = None,
        event_bus: Optional[EventBus] = None,
        context_manager: Optional[Any] = None,
        error_collector: Optional[ErrorCollector] = None,
    ):
        settings = get_settings()
        self._event_bus = event_bus
        self._context_manager = context_manager
        self._error_collector = error_collector or ErrorCollector()

        backend_value = backend or settings.llm_backend
        allowed_backends = {"deepseek", "kimi", "ollama", "openai-compatible"}
        if backend_value not in allowed_backends:
            raise ValueError(
                f"不支持的 LLM backend: {backend_value}，支持: {', '.join(sorted(allowed_backends))}"
            )
        normalized_backend = cast(
            Literal["deepseek", "kimi", "ollama", "openai-compatible"],
            backend_value,
        )

        def _emit_usage(usage: Dict[str, Any]) -> None:
            if not self._event_bus:
                return
            try:
                self._event_bus.emit_type(EventType.TOKEN_USAGE, usage)
            except Exception:
                pass

        self.llm = llm or LLMClient(
            backend=normalized_backend,
            api_key=api_key or settings.get_api_key_for_backend(normalized_backend),
            base_url=base_url or settings.get_base_url_for_backend(normalized_backend),
            ollama_url=ollama_url or settings.ollama_url,
            model=model or settings.get_model_for_backend(normalized_backend),
            on_usage=_emit_usage,
        )
        if llm is not None and getattr(self.llm, "on_usage", None) is None:
            self.llm.on_usage = _emit_usage

        self.reasoning_engine = ReasoningEngine(
            self.llm,
            event_bus=event_bus,
            backend=normalized_backend,
            api_key=api_key or settings.get_api_key_for_backend(normalized_backend),
            base_url=base_url or settings.get_base_url_for_backend(normalized_backend),
            ollama_url=ollama_url or settings.ollama_url,
            model=model or settings.get_model_for_backend(normalized_backend),
        )
        self.action_executor = ActionExecutor(
            event_bus=event_bus,
            context_manager=context_manager,
            error_collector=self._error_collector,
        )
        self.observer = Observer()
        self.iteration_controller = IterationController(
            self.llm, error_collector=self._error_collector
        )

        # None / <=0 表示不设上限，持续调整直到可求解或致命失败
        self.max_iterations = max_iterations if (max_iterations or 0) > 0 else None

        # PlanRuntime / TaskRuntime 同步：把 ReActTaskPlan 的状态镜像到
        # .port_sessions/{plan_runtime,task_runtime}.json，便于审计与桌面端展示。
        self._plan_sync = None
        try:
            from agent.clawcode_bridge.plan_sync import PlanSync

            self._plan_sync = PlanSync(project_root=get_project_root())
        except Exception as exc:  # pragma: no cover - 容错
            logger.debug("PlanSync 初始化失败：%s", exc)
            self._plan_sync = None

    def _sync_plan_runtime(self, plan: ReActTaskPlan, *, phase: str) -> None:
        """把 plan 同步到 PlanRuntime/TaskRuntime，并广播 PLAN_RUNTIME_SYNC。"""
        if self._plan_sync is None:
            return
        try:
            mutation = self._plan_sync.sync(plan, explanation=f"phase={phase}")
        except Exception as exc:  # pragma: no cover
            logger.debug("plan_sync.sync 失败：%s", exc)
            return
        if self._event_bus is None:
            return
        try:
            payload = {"phase": phase, **{k: v for k, v in mutation.items() if k != "error"}}
            if "error" in mutation:
                payload["error"] = mutation["error"]
            self._event_bus.emit_type(EventType.PLAN_RUNTIME_SYNC, payload)
        except Exception:
            pass

    def _run_end_success_and_message(self, plan: ReActTaskPlan) -> tuple[bool, str]:
        """计算 RUN_END 的 success 与 message。"""
        if plan.status == "completed":
            path = (getattr(plan, "model_path", None) or "").strip()
            tail = (plan.error or "").strip()
            if path:
                loc = f"求解成功。模型位置：{path}"
                return True, f"{tail}\n{loc}".strip() if tail and tail not in loc else loc
            return True, tail or "已完成"
        if plan.status == "failed":
            return False, (plan.error or "任务失败").strip()
        if plan.error:
            return False, plan.error.strip()
        return False, "任务未完成（尚未得到可求解结果）"

    def run(
        self,
        user_input: str,
        output_filename: Optional[str] = None,
        memory_context: Optional[str] = None,
        output_dir: Optional[Path] = None,
        clarifying_answers: Optional[List[ClarifyingAnswer]] = None,
        given_plan: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        执行完整的 ReAct 流程

        Args:
            user_input: 用户自然语言输入
            output_filename: 输出文件名（可选）

        Returns:
            生成的模型文件路径

        Raises:
            RuntimeError: 执行失败
        """
        logger.info("=" * 60)
        logger.info("开始 ReAct 流程")
        logger.info("=" * 60)
        logger.info(f"用户输入: {user_input}")

        if self._event_bus:
            self._event_bus.emit_type(EventType.PLAN_START, {"user_input": user_input})
            self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "planning"})
            try:
                from agent.executor.compute_backend import detect_compute_backend

                self._event_bus.emit_type(
                    EventType.COMPUTE_BACKEND, detect_compute_backend().to_dict()
                )
            except Exception:
                pass

        # 初始化任务计划（若给定 plan 则直接使用，否则由推理引擎规划）
        plan = self._initial_plan(
            user_input,
            output_filename,
            memory_context,
            output_dir=output_dir,
            clarifying_answers=clarifying_answers,
            given_plan=given_plan,
        )

        if self._event_bus:
            modeling_steps = _serialize_modeling_steps(plan)
            steps_summary = [
                {
                    "action": s["action"],
                    "step_type": s["step_type"],
                    "label": s["label"],
                    "why": s["why"],
                    "inputs": s["inputs"],
                }
                for s in modeling_steps
            ]
            requires_clarification = bool(plan.clarifying_questions and not clarifying_answers)
            plan_description = getattr(plan, "plan_description", None) or ""
            self._event_bus.emit_type(
                EventType.PLAN_END,
                {
                    "steps": steps_summary,
                    "model_name": plan.model_name,
                    "plan_description": plan_description,
                    "stop_after_step": getattr(plan, "stop_after_step", None),
                    "clarifying_questions": getattr(plan, "clarifying_questions", None),
                    "requires_clarification": requires_clarification,
                    "case_library_suggestions": getattr(plan, "case_library_suggestions", None),
                },
            )
            # 推理思路 + 细致建模过程（供前端独立卡片展示）
            self._event_bus.emit_type(
                EventType.DECISION,
                {
                    "kind": "plan_rationale",
                    "title": "规划推理思路",
                    "reasoning": plan_description
                    or "已按 COMSOL 标准流程拆解为可执行步骤，目标是产出可求解模型。",
                    "basis": (user_input or "")[:500],
                    "details": {
                        "model_name": plan.model_name,
                        "stop_after_step": getattr(plan, "stop_after_step", None) or "solve",
                        "step_count": len(modeling_steps),
                    },
                },
            )
            self._event_bus.emit_type(
                EventType.MODELING_PROCESS,
                {
                    "title": "建模细致过程",
                    "summary": plan_description
                    or "按几何 → 材料 → 物理场 → 网格 → 研究 → 求解推进。",
                    "steps": modeling_steps,
                },
            )
            if getattr(plan, "plan_confirmed", False):
                self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "plan_confirmed"})

        # 把刚生成的计划同步到 PlanRuntime/TaskRuntime
        self._sync_plan_runtime(plan, phase="initial_plan")

        # Plan-only 模式：若存在澄清问题且本次未带 clarifying_answers，则仅返回计划，等待前端提问
        if plan.clarifying_questions and not clarifying_answers:
            if self._event_bus:
                self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "planning_clarify"})
            # 使用特定错误类型由上层捕获并转换为「计划已生成，等待澄清问题」
            raise PlanNeedsClarification("计划已生成，等待澄清问题", plan)

        # ReAct 主循环：不以调整次数作为结束条件；直到可求解完成，或致命/无效迭代中断。
        # max_iterations 仅作可选调试上限（None = 不限制）。
        iteration = 0
        while True:
            iteration += 1
            if self.max_iterations is not None and iteration > self.max_iterations:
                logger.warning(
                    "调试上限 max_iterations=%s 已触达；默认生产路径不应设置该上限",
                    self.max_iterations,
                )
                if not plan.error:
                    plan.error = "任务未完成（尚未得到可求解结果）"
                break
            logger.info("\n--- 第 %s 轮（持续调整直至可求解）---", iteration)
            if self._event_bus:
                self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "thinking"})

            try:
                thought = self.think(plan)
                logger.info("[Think] %s", thought.get("action", "N/A"))
                if self._event_bus:
                    self._event_bus.emit_type(EventType.THINK_CHUNK, {"thought": thought})

                if thought.get("action") == "complete":
                    logger.info("[Act] 任务已完成")
                    if self._is_all_steps_complete(plan):
                        plan.status = "completed"
                    elif plan.execution_path:
                        plan.status = "failed"
                        plan.error = "收到 complete 信号，但仍有未完成步骤"
                    else:
                        plan.status = "failed"
                        plan.error = "收到 complete 信号，但执行路径为空"
                    if self._event_bus:
                        self._event_bus.emit_type(EventType.ACTION_END, {"action": "complete"})
                    break

                if self._event_bus:
                    self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "executing"})
                    self._event_bus.emit_type(EventType.ACTION_START, {"thought": thought})
                executed_step = plan.get_current_step()
                result = self.act(plan, thought)
                step_id = executed_step.step_id if executed_step else "unknown"
                self._error_collector.submit(step_id, "act", {"result": result})
                logger.info("[Act] 执行结果: %s", result.get("status", "N/A"))
                if self._event_bus:
                    payload: Dict[str, Any] = {"result": result}
                    ui = result.get("ui") if isinstance(result, dict) else None
                    if ui:
                        payload["ui"] = ui
                    self._event_bus.emit_type(EventType.EXEC_RESULT, payload)

                if self._event_bus:
                    self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "observing"})
                observation = self.observe(plan, result, executed_step=executed_step)
                self._error_collector.submit(
                    step_id,
                    "observe",
                    {
                        "observation": {"message": observation.message, "status": observation.status},
                        "status": observation.status,
                        "message": observation.message,
                    },
                )
                logger.info("[Observe] %s", observation.message)
                if self._event_bus:
                    self._event_bus.emit_type(
                        EventType.OBSERVATION,
                        {"observation": observation.message, "status": observation.status},
                    )

                # 把每一轮 act/observe 后的状态同步给 PlanRuntime
                self._sync_plan_runtime(plan, phase=f"iter_{iteration}")

                # 判断是否完成
                if observation.status == "success" and self._is_all_steps_complete(plan):
                    plan.status = "completed"
                    logger.info("✅ 所有步骤已完成")
                    break

                # 执行错误：不直接退出，先重新思考与规划；仅当控制器标记为致命错误时才退出
                if observation.status == "error":
                    logger.info(
                        "检测到错误，将根据错误信息重新规划并继续: %s",
                        (observation.message or "")[:200],
                    )
                    if self._event_bus:
                        self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "iterating"})
                    plan = self.iterate(plan, observation)
                    self._sync_plan_runtime(plan, phase="iterate_error")
                    if plan.status == "failed":
                        logger.error("控制器判定为不可恢复，已中断: %s", plan.error)
                        break
                    logger.info(
                        "[调整] 计划已更新，将从步骤 %s 重新执行", plan.current_step_index + 1
                    )
                    continue

                # 警告时尝试迭代更新计划
                if observation.status == "warning":
                    if self.iteration_controller.should_iterate(plan, observation):
                        if self._event_bus:
                            self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "iterating"})
                        plan = self.iterate(plan, observation)
                        self._sync_plan_runtime(plan, phase="iterate_warning")
                        logger.info("[调整] 计划已更新，当前步骤: %s", plan.current_step_index)

            except Exception as e:
                logger.error("第 %s 轮失败: %s", iteration, e)
                self._error_collector.submit("run", "exception", {"message": str(e)})
                plan.status = "failed"
                plan.error = str(e)
                final_path = getattr(plan, "model_path", None)
                if final_path:
                    try:
                        final_path = str(Path(final_path).resolve()) if Path(final_path).exists() else None
                    except Exception:
                        final_path = None
                if self._event_bus:
                    self._event_bus.emit_type(
                        EventType.RUN_END,
                        {"model_path": final_path, "success": False, "message": str(e)},
                    )
                    try:
                        from agent.react.next_actions import next_actions_event_payload

                        if not plan.error:
                            plan.error = str(e)
                        self._event_bus.emit_type(
                            EventType.NEXT_ACTIONS,
                            next_actions_event_payload(
                                plan, success=False, model_path=final_path
                            ),
                        )
                    except Exception:
                        pass
                raise RuntimeError(f"ReAct 流程失败: {e}") from e

        # 同步最终状态到 PlanRuntime，方便审计/桌面端读
        self._sync_plan_runtime(plan, phase="run_end")

        # 成功时清理过程模型，只留 *_latest.mph；再发出 RUN_END 供前端展示路径与打开
        end_success, _ = self._run_end_success_and_message(plan)
        if end_success:
            try:
                self.action_executor.cleanup_stage_models(plan)
            except Exception:
                logger.debug("run_end 清理过程模型失败", exc_info=True)

        final_path = getattr(plan, "model_path", None)
        if final_path:
            try:
                p = Path(final_path)
                if p.exists():
                    final_path = str(p.resolve())
                    plan.model_path = final_path
            except Exception:
                final_path = None

        end_success, end_message = self._run_end_success_and_message(plan)
        if self._event_bus:
            self._event_bus.emit_type(
                EventType.RUN_END,
                {
                    "model_path": final_path,
                    "success": end_success,
                    "message": end_message,
                },
            )
            try:
                from agent.react.next_actions import next_actions_event_payload

                self._event_bus.emit_type(
                    EventType.NEXT_ACTIONS,
                    next_actions_event_payload(
                        plan, success=end_success, model_path=final_path
                    ),
                )
            except Exception:
                logger.debug("emit next_actions failed", exc_info=True)

        if plan.status != "completed":
            if end_success:
                if final_path and Path(final_path).exists():
                    logger.info("以外层末次观察为准结束")
                    return Path(final_path)
                raise RuntimeError(end_message or "模型文件未生成")
            base_msg = end_message or "任务失败"
            msg = base_msg
            if final_path:
                msg = f"{msg}；模型已部分生成: {final_path}"
            if plan.status == "failed" and (plan.error or "").startswith(REORCHESTRATE_PREFIX):
                raise ReActNeedsReorchestrate(plan.error)
            raise RuntimeError(msg)

        if final_path and Path(final_path).exists():
            logger.info(f"✅ 模型已生成: {final_path}")
            return Path(final_path)

        raise RuntimeError("模型文件未生成")

    def think(self, plan: ReActTaskPlan) -> Dict[str, Any]:
        """
        推理当前状态，规划下一步行动

        Args:
            plan: 当前任务计划

        Returns:
            思考结果，包含下一步行动
        """
        plan.status = "planning"

        # 使用推理引擎进行推理，并补齐可读决策依据
        thought = self.reasoning_engine.reason(plan)
        current = plan.get_current_step()
        action = str(thought.get("action") or "")
        params = thought.get("parameters") if isinstance(thought.get("parameters"), dict) else {}
        if not params and current:
            params = current.parameters or {}
            thought["parameters"] = params
        label = _STEP_LABELS.get(action, action or "下一步")
        why = _STEP_WHY.get(action, "按当前计划推进，服务最终可求解闭环。")
        highlights = _param_highlights(params if isinstance(params, dict) else {})
        progress = f"{plan.current_step_index + 1}/{max(len(plan.execution_path), 1)}"
        reasoning = str(thought.get("reasoning") or "").strip()
        if not reasoning or reasoning.startswith("执行步骤:") or reasoning.startswith("继续执行"):
            reasoning = f"第 {progress} 步决定执行「{label}」。{why}"
            if highlights:
                reasoning += " 本步关键输入：" + "；".join(highlights[:3])
            thought["reasoning"] = reasoning
        thought["basis"] = why
        thought["label"] = label
        thought["progress"] = progress
        thought["input_highlights"] = highlights

        if self._event_bus and action not in ("", "complete"):
            self._event_bus.emit_type(
                EventType.DECISION,
                {
                    "kind": "step_decision",
                    "title": f"决策：执行 {label}",
                    "reasoning": thought.get("reasoning"),
                    "basis": why,
                    "action": action,
                    "progress": progress,
                    "inputs": highlights,
                    "details": {
                        "step_type": getattr(current, "step_type", None),
                        "parameters": params,
                    },
                },
            )

        return thought

    def act(self, plan: ReActTaskPlan, thought: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行具体的建模操作

        Args:
            plan: 当前任务计划
            thought: 思考结果

        Returns:
            执行结果
        """
        plan.status = "executing"

        action = thought.get("action")
        if not action:
            return {"status": "error", "message": "未指定行动"}

        # 获取当前步骤
        current_step = plan.get_current_step()
        if current_step:
            # 以 thought.action 为准，确保 think->act 路由一致
            if current_step.action != action:
                current_step.action = action
            if thought.get("parameters"):
                current_step.parameters.update(thought.get("parameters", {}))
        else:
            # 如果没有当前步骤，根据 action 创建新步骤
            current_step = self._create_step_from_action(action, thought)
            plan.execution_path.append(current_step)
            plan.current_step_index = len(plan.execution_path) - 1

        current_step.status = "running"

        try:
            # 执行行动
            result = self.action_executor.execute(plan, current_step, thought)

            result_status = result.get("status")
            if result_status == "success":
                current_step.status = "completed"
            elif result_status == "warning":
                current_step.status = "warning"
            elif result_status == "skipped":
                current_step.status = "skipped"
            else:
                current_step.status = "failed"
            current_step.result = result

            # 更新计划状态
            if result_status in ("success", "warning", "skipped"):
                # 移动到下一步
                if plan.current_step_index < len(plan.execution_path) - 1:
                    plan.current_step_index += 1
                else:
                    # 所有步骤完成（允许 warning/skipped 作为可结束态，最终由完整性检查兜底）
                    if self._is_all_steps_complete(plan):
                        plan.status = "completed"

            return result

        except Exception as e:
            current_step.status = "failed"
            current_step.result = {"error": str(e)}
            logger.error(f"执行步骤失败: {e}")
            return {"status": "error", "message": str(e)}

    def observe(
        self,
        plan: ReActTaskPlan,
        result: Dict[str, Any],
        executed_step: Optional[ExecutionStep] = None,
    ) -> Observation:
        """
        观察执行结果

        Args:
            plan: 当前任务计划
            result: 执行结果

        Returns:
            观察结果
        """
        plan.status = "observing"

        current_step = executed_step or plan.get_current_step()
        if not current_step:
            return Observation(
                observation_id=str(uuid4()),
                step_id="unknown",
                status="error",
                message="无法观察：没有当前步骤",
            )

        # 使用观察器进行观察（绑定本轮实际执行的步骤）
        observation = self.observer.observe(plan, current_step, result)

        # 添加到计划
        plan.add_observation(observation)

        return observation

    def iterate(self, plan: ReActTaskPlan, observation: Observation) -> ReActTaskPlan:
        """
        根据观察结果改进计划

        Args:
            plan: 当前任务计划
            observation: 观察结果

        Returns:
            更新后的计划
        """
        plan.status = "iterating"

        # 使用迭代控制器更新计划
        updated_plan = self.iteration_controller.update_plan(plan, observation)
        adjust_summary = getattr(
            self.iteration_controller, "last_adjust_summary", None
        ) or ""
        analysis_report = getattr(
            self.iteration_controller, "last_analysis_report", None
        )
        if self._event_bus:
            details = {
                "observation_status": observation.status,
                "current_step_index": updated_plan.current_step_index + 1,
                "total_steps": len(updated_plan.execution_path),
                "plan_status": updated_plan.status,
                "plan_error": updated_plan.error,
            }
            if analysis_report is not None:
                try:
                    details["analysis"] = {
                        "error_summary": analysis_report.error_summary,
                        "root_cause": analysis_report.root_cause_hypothesis,
                        "selected": analysis_report.selected_hypothesis_id,
                        "hypotheses": [
                            {
                                "id": h.id,
                                "title": h.title,
                                "angle": h.angle,
                                "confidence": h.confidence,
                                "tried": h.tried,
                            }
                            for h in (analysis_report.hypotheses or [])[:5]
                        ],
                        "evidence_sources": [
                            e.source for e in (analysis_report.evidence or [])[:12]
                        ],
                    }
                except Exception:
                    pass
            self._event_bus.emit_type(
                EventType.DECISION,
                {
                    "kind": "adjust_decision" if analysis_report is None else "error_analysis",
                    "title": (
                        "决策：分析 Agent 多角度修复"
                        if analysis_report is not None
                        else "决策：根据观察结果调整计划"
                    ),
                    "reasoning": adjust_summary
                    or "检测到执行偏差，已回退/修补相关步骤并继续朝可求解目标推进。",
                    "basis": (observation.message or "")[:500],
                    "details": details,
                },
            )
            # 调整后刷新细致过程面板
            self._event_bus.emit_type(
                EventType.MODELING_PROCESS,
                {
                    "title": "调整后的建模过程",
                    "summary": adjust_summary
                    or "计划已更新，将从回退点继续执行。",
                    "steps": _serialize_modeling_steps(updated_plan),
                },
            )

        return updated_plan

    def _initial_plan(
        self,
        user_input: str,
        output_filename: Optional[str] = None,
        memory_context: Optional[str] = None,
        output_dir: Optional[Path] = None,
        clarifying_answers: Optional[List[ClarifyingAnswer]] = None,
        given_plan: Optional[Dict[str, Any]] = None,
    ) -> ReActTaskPlan:
        """
        初始化任务计划。若 given_plan 存在（Plan 模式已确定计划），则直接转为 ReActTaskPlan；
        否则使用推理引擎理解需求并规划。
        """
        task_id = str(uuid4())
        model_name = (
            output_filename.replace(".mph", "") if output_filename else f"model_{task_id[:8]}"
        )

        if given_plan:
            # Plan 模式：从已确定的 plan 字典构建 ReActTaskPlan，跳过编排器
            from agent.react.reasoning_engine import _task_plan_to_execution_path
            from agent.schemas.geometry import GeometryPlan
            from agent.schemas.material import MaterialPlan
            from agent.schemas.mesh import MeshPlan
            from agent.schemas.physics import PhysicsPlan
            from agent.schemas.study import StudyPlan
            from agent.schemas.task import GlobalDefinitionPlan, TaskPlan

            g = given_plan.get("geometry")
            m = given_plan.get("material")
            mesh = given_plan.get("mesh")
            p = given_plan.get("physics")
            s = given_plan.get("study")
            globals_plan = []
            for item in given_plan.get("global_definitions", []) or []:
                try:
                    globals_plan.append(GlobalDefinitionPlan.model_validate(item))
                except Exception:
                    continue
            task_plan = TaskPlan(
                geometry=GeometryPlan.from_dict(g) if g else None,
                material=MaterialPlan.from_dict(m) if m else None,
                mesh=MeshPlan.model_validate(mesh) if mesh else None,
                physics=PhysicsPlan.model_validate(p) if p else None,
                study=StudyPlan.model_validate(s) if s else None,
                global_definitions=globals_plan,
            )
            execution_path = _task_plan_to_execution_path(task_plan)
            reasoning_path = self.reasoning_engine.plan_reasoning_path(execution_path)
            plan_description = (given_plan.get("plan_description") or "").strip() or None
            stop_after = execution_path[-1].action if execution_path else None
            initial_plan = ReActTaskPlan(
                task_id=task_id,
                model_name=model_name,
                user_input=user_input,
                execution_path=execution_path,
                reasoning_path=reasoning_path,
                status="planning",
                plan_description=plan_description,
                stop_after_step=stop_after,
            )
            initial_plan.geometry_plan = task_plan.geometry
            initial_plan.material_plan = task_plan.material
            initial_plan.physics_plan = task_plan.physics
            initial_plan.mesh_plan = task_plan.mesh
            initial_plan.study_plan = task_plan.study
            initial_plan.global_definitions = task_plan.global_definitions
            initial_plan.clarifying_questions = None
            initial_plan.clarifying_answers = None
            initial_plan.discussion_card_ref = given_plan.get("discussion_card_ref")
            initial_plan.plan_confirmed = bool(given_plan.get("plan_confirmed"))
        else:
            initial_plan = self.reasoning_engine.understand_and_plan(
                user_input,
                model_name,
                memory_context=memory_context,
                clarifying_answers=clarifying_answers,
            )
            initial_plan.geometry_plan = None

        if output_dir is not None:
            initial_plan.output_dir = str(output_dir.resolve())
        return initial_plan

    def _create_step_from_action(self, action: str, thought: Dict[str, Any]) -> ExecutionStep:
        """
        根据行动创建执行步骤

        Args:
            action: 行动类型
            thought: 思考结果

        Returns:
            执行步骤
        """
        step_id = str(uuid4())

        # 根据 action 确定步骤类型
        step_type_map = {
            "create_geometry": "geometry",
            "define_globals": "global",
            "add_material": "material",
            "update_material_property": "material",
            "add_physics": "physics",
            "generate_mesh": "mesh",
            "configure_study": "study",
            "solve": "solve",
            "import_geometry": "geometry_io",
            "create_selection": "selection",
            "export_results": "postprocess",
            "evaluate_results": "postprocess",
            "set_parameters": "postprocess",
            "call_official_api": "java_api",
        }

        step_type = step_type_map.get(action, "geometry")

        return ExecutionStep(
            step_id=step_id,
            step_type=step_type,
            action=action,
            parameters=thought.get("parameters", {}),
            status="pending",
        )

    def _is_recoverable_error(self, plan: ReActTaskPlan, observation: Observation) -> bool:
        """
        判断是否为可恢复错误：求解/研究/网格/物理/材料等步骤因前置步骤不完整而失败，
        可通过回退到对应步骤补充后重跑；API 级致命错误则不可恢复。
        """
        msg = (observation.message or "").lower()
        # 致命：Python/Java 属性或环境错误，无法通过重做步骤修复
        if "object has no attribute" in msg or "has no attribute" in msg:
            return False
        if "cannot find" in msg and ("project root" in msg or "jvm" in msg or "jar" in msg):
            return False
        # 可恢复：COMSOL 求解或特征报错，通常缺材料属性/边界等，可回退到材料或物理步骤补充
        if (
            "求解失败" in observation.message
            or "未定义" in msg
            or "材料属性" in msg
            or "所需的" in msg
        ):
            return True
        if "flException" in msg or "特征遇到问题" in observation.message:
            return True
        # 同一类错误连续调整过多则不再视为可恢复，避免死循环
        recent = plan.observations[-4:] if len(plan.observations) >= 4 else plan.observations
        error_count = sum(1 for o in recent if o.status == "error")
        if error_count >= 3:
            return False
        return False

    def _is_all_steps_complete(self, plan: ReActTaskPlan) -> bool:
        """检查是否所有步骤都已完成"""
        if not plan.execution_path:
            return False

        return all(
            step.status in ("completed", "warning", "skipped") for step in plan.execution_path
        )

    def _generate_integration_suggestions(self, plan: ReActTaskPlan) -> Optional[str]:
        """
        在因能力不足结束工作流前，根据用户需求、错误信息与已尝试操作，
        生成建议集成的 COMSOL Java API 接口说明，供后续开发扩展。
        """
        if not plan.execution_path and not plan.error:
            return None
        iteration_count = len(plan.iterations) if plan.iterations else 0
        if iteration_count == 0 and not plan.error:
            return None
        steps_desc = [s.action for s in plan.execution_path] if plan.execution_path else []
        last_errors = []
        if plan.observations:
            for o in plan.observations[-3:]:
                if o.status == "error" and o.message:
                    last_errors.append(o.message[:300])
        err_summary = "\n".join(last_errors) if last_errors else (plan.error or "")
        try:
            prompt = f"""当前 COMSOL 建模 Agent 已集成的操作包括：几何创建(create_geometry)、材料添加(add_material)、仅更新已有材料属性(update_material_property)、物理场添加(add_physics)、网格生成(generate_mesh)、研究配置(configure_study)、求解(solve)。这些操作无法满足所有场景。

用户需求：{plan.user_input[:500]}
最后一次错误摘要：{err_summary[:800]}
已执行步骤：{steps_desc}
调整次数：{iteration_count}

请根据上述失败原因与已尝试的操作，简要列出建议集成的 COMSOL Java API 接口（例如：删除或重命名材料节点、查询模型中已有材料/物理场名称、在已有材料上更新属性等），便于后续开发扩展。每条一行，简洁具体。若无法推断可回答：暂无明确建议。"""
            out = self.llm.call(prompt, temperature=0.1)
            out = (out or "").strip()
            if out and "暂无明确建议" not in out:
                return out[:1500]
        except Exception as e:
            logger.warning("生成集成建议失败: %s", e)
        return None
