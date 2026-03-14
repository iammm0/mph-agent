"""ReAct Agent 核心类"""
from pathlib import Path
from typing import Optional, Dict, Any, List
from uuid import uuid4

from agent.react.reasoning_engine import ReasoningEngine
from agent.react.action_executor import ActionExecutor
from agent.react.observer import Observer
from agent.react.iteration_controller import IterationController
from agent.react.exceptions import PlanNeedsClarification
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.utils.config import get_settings
from agent.core.events import EventBus, EventType
from schemas.task import ReActTaskPlan, ExecutionStep, Observation, ClarifyingAnswer

logger = get_logger(__name__)


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
        max_iterations: int = 10,
        event_bus: Optional[EventBus] = None,
        context_manager: Optional[Any] = None,
    ):
        settings = get_settings()
        self._event_bus = event_bus
        self._context_manager = context_manager

        self.llm = llm or LLMClient(
            backend=backend or settings.llm_backend,
            api_key=api_key or settings.get_api_key_for_backend(backend or settings.llm_backend),
            base_url=base_url or settings.get_base_url_for_backend(backend or settings.llm_backend),
            ollama_url=ollama_url or settings.ollama_url,
            model=model or settings.get_model_for_backend(backend or settings.llm_backend),
        )

        self.reasoning_engine = ReasoningEngine(
            self.llm,
            event_bus=event_bus,
            backend=backend or settings.llm_backend,
            api_key=api_key or settings.get_api_key_for_backend(backend or settings.llm_backend),
            base_url=base_url or settings.get_base_url_for_backend(backend or settings.llm_backend),
            ollama_url=ollama_url or settings.ollama_url,
            model=model or settings.get_model_for_backend(backend or settings.llm_backend),
        )
        self.action_executor = ActionExecutor(event_bus=event_bus, context_manager=context_manager)
        self.observer = Observer()
        self.iteration_controller = IterationController(self.llm)

        self.max_iterations = max_iterations
    
    def run(
        self,
        user_input: str,
        output_filename: Optional[str] = None,
        memory_context: Optional[str] = None,
        output_dir: Optional[Path] = None,
        clarifying_answers: Optional[List[ClarifyingAnswer]] = None,
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

        # 初始化任务计划（注入本会话的摘要记忆与澄清答案）
        plan = self._initial_plan(
            user_input,
            output_filename,
            memory_context,
            output_dir=output_dir,
            clarifying_answers=clarifying_answers,
        )

        if self._event_bus:
            steps_summary = [{"action": s.action, "step_type": s.step_type} for s in plan.execution_path]
            requires_clarification = bool(plan.clarifying_questions and not clarifying_answers)
            self._event_bus.emit_type(
                EventType.PLAN_END,
                {
                    "steps": steps_summary,
                    "model_name": plan.model_name,
                    "plan_description": getattr(plan, "plan_description", None) or "",
                    "stop_after_step": getattr(plan, "stop_after_step", None),
                    "clarifying_questions": getattr(plan, "clarifying_questions", None),
                    "requires_clarification": requires_clarification,
                    "case_library_suggestions": getattr(plan, "case_library_suggestions", None),
                },
            )

        # Plan-only 模式：若存在澄清问题且本次未带 clarifying_answers，则仅返回计划，等待前端提问
        if plan.clarifying_questions and not clarifying_answers:
            # 使用特定错误类型由上层捕获并转换为「计划已生成，等待澄清问题」
            raise PlanNeedsClarification("计划已生成，等待澄清问题", plan)
        
        # ReAct 主循环
        for iteration in range(self.max_iterations):
            logger.info("\n--- 迭代 %s/%s ---", iteration + 1, self.max_iterations)
            if self._event_bus:
                self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "thinking"})

            try:
                thought = self.think(plan)
                logger.info("[Think] %s", thought.get("action", "N/A"))
                if self._event_bus:
                    self._event_bus.emit_type(EventType.THINK_CHUNK, {"thought": thought})

                if thought.get("action") == "complete":
                    logger.info("[Act] 任务已完成")
                    if self._event_bus:
                        self._event_bus.emit_type(EventType.ACTION_END, {"action": "complete"})
                    break

                if self._event_bus:
                    self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "executing"})
                    self._event_bus.emit_type(EventType.ACTION_START, {"thought": thought})
                result = self.act(plan, thought)
                logger.info("[Act] 执行结果: %s", result.get("status", "N/A"))
                if self._event_bus:
                    payload: Dict[str, Any] = {"result": result}
                    ui = result.get("ui") if isinstance(result, dict) else None
                    if ui:
                        payload["ui"] = ui
                    self._event_bus.emit_type(EventType.EXEC_RESULT, payload)

                if self._event_bus:
                    self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "observing"})
                observation = self.observe(plan, result)
                logger.info("[Observe] %s", observation.message)
                if self._event_bus:
                    self._event_bus.emit_type(EventType.OBSERVATION, {"observation": observation.message, "status": observation.status})
                
                # 判断是否完成
                if observation.status == "success" and self._is_all_steps_complete(plan):
                    plan.status = "completed"
                    logger.info("✅ 所有步骤已完成")
                    break

                # 执行错误：不直接退出，先重新思考与规划；仅当控制器标记为致命错误时才退出
                if observation.status == "error":
                    logger.info("检测到错误，将根据错误信息重新规划并继续: %s", (observation.message or "")[:200])
                    if self._event_bus:
                        self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "iterating"})
                    plan = self.iterate(plan, observation)
                    if plan.status == "failed":
                        logger.error("迭代控制器判定为不可恢复，已中断: %s", plan.error)
                        break
                    logger.info("[Iterate] 计划已更新，将从步骤 %s 重新执行", plan.current_step_index + 1)
                    continue

                # 警告时尝试迭代更新计划
                if observation.status == "warning":
                    if self._event_bus:
                        self._event_bus.emit_type(EventType.TASK_PHASE, {"phase": "iterating"})
                    plan = self.iterate(plan, observation)
                    logger.info(f"[Iterate] 计划已更新，当前步骤: {plan.current_step_index}")
                
            except Exception as e:
                logger.error(f"迭代 {iteration + 1} 失败: {e}")
                plan.status = "failed"
                plan.error = str(e)
                raise RuntimeError(f"ReAct 流程失败: {e}") from e
        
        # 检查最终状态
        if plan.status != "completed":
            # 统一构造错误信息；若模型文件已存在，则提示“模型已部分生成”，便于用户后续在 COMSOL 中继续处理。
            base_msg = plan.error or (
                f"任务未完成（达到最大迭代次数: {self.max_iterations}）"
                if plan.status != "failed"
                else "任务失败"
            )
            msg = base_msg or "任务失败"
            partial_path = getattr(plan, "model_path", None)
            if partial_path:
                try:
                    model_path = Path(partial_path)
                    if model_path.exists():
                        msg = f"{msg}；模型已部分生成: {model_path}"
                except Exception:
                    pass
            raise RuntimeError(msg)
        
        # 保存模型
        if plan.model_path:
            model_path = Path(plan.model_path)
            if model_path.exists():
                logger.info(f"✅ 模型已生成: {model_path}")
                return model_path
        
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
        
        # 使用推理引擎进行推理
        thought = self.reasoning_engine.reason(plan)
        
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
        if not current_step:
            # 如果没有当前步骤，根据 action 创建新步骤
            current_step = self._create_step_from_action(action, thought)
            plan.execution_path.append(current_step)
            plan.current_step_index = len(plan.execution_path) - 1
        
        current_step.status = "running"
        
        try:
            # 执行行动
            result = self.action_executor.execute(plan, current_step, thought)
            
            current_step.status = "completed" if result.get("status") == "success" else "failed"
            current_step.result = result
            
            # 更新计划状态
            if result.get("status") == "success":
                # 移动到下一步
                if plan.current_step_index < len(plan.execution_path) - 1:
                    plan.current_step_index += 1
                else:
                    # 所有步骤完成
                    plan.status = "completed"
            
            return result
            
        except Exception as e:
            current_step.status = "failed"
            current_step.result = {"error": str(e)}
            logger.error(f"执行步骤失败: {e}")
            return {"status": "error", "message": str(e)}
    
    def observe(self, plan: ReActTaskPlan, result: Dict[str, Any]) -> Observation:
        """
        观察执行结果
        
        Args:
            plan: 当前任务计划
            result: 执行结果
        
        Returns:
            观察结果
        """
        plan.status = "observing"
        
        current_step = plan.get_current_step()
        if not current_step:
            return Observation(
                observation_id=str(uuid4()),
                step_id="unknown",
                status="error",
                message="无法观察：没有当前步骤"
            )
        
        # 使用观察器进行观察
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
        
        return updated_plan
    
    def _initial_plan(
        self,
        user_input: str,
        output_filename: Optional[str] = None,
        memory_context: Optional[str] = None,
        output_dir: Optional[Path] = None,
        clarifying_answers: Optional[List[ClarifyingAnswer]] = None,
    ) -> ReActTaskPlan:
        """
        初始化任务计划

        Args:
            user_input: 用户输入
            output_filename: 输出文件名
            memory_context: 会话摘要等上下文
            output_dir: 模型与操作记录输出目录（有会话时与 context 同目录）

        Returns:
            初始化的任务计划
        """
        task_id = str(uuid4())
        model_name = output_filename.replace(".mph", "") if output_filename else f"model_{task_id[:8]}"

        # 使用推理引擎理解需求并规划（可注入会话摘要与澄清答案）
        initial_plan = self.reasoning_engine.understand_and_plan(
            user_input,
            model_name,
            memory_context=memory_context,
            clarifying_answers=clarifying_answers,
        )

        # 添加 geometry_plan 属性占位符（用于存储几何计划）
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
            "add_material": "material",
            "add_physics": "physics",
            "generate_mesh": "mesh",
            "configure_study": "study",
            "solve": "solve",
            "import_geometry": "geometry_io",
            "create_selection": "selection",
            "export_results": "postprocess",
        }
        
        step_type = step_type_map.get(action, "geometry")
        
        return ExecutionStep(
            step_id=step_id,
            step_type=step_type,
            action=action,
            parameters=thought.get("parameters", {}),
            status="pending"
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
        if "求解失败" in observation.message or "未定义" in msg or "材料属性" in msg or "所需的" in msg:
            return True
        if "flException" in msg or "特征遇到问题" in observation.message:
            return True
        # 同一类错误连续迭代过多则不再视为可恢复，避免死循环
        recent = plan.observations[-4:] if len(plan.observations) >= 4 else plan.observations
        error_count = sum(1 for o in recent if o.status == "error")
        if error_count >= 3:
            return False
        return False
    
    def _is_all_steps_complete(self, plan: ReActTaskPlan) -> bool:
        """检查是否所有步骤都已完成"""
        if not plan.execution_path:
            return False
        
        return all(step.status == "completed" for step in plan.execution_path)

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
            prompt = f"""当前 COMSOL 建模 Agent 已集成的操作包括：几何创建(create_geometry)、材料添加(add_material)、物理场添加(add_physics)、网格生成(generate_mesh)、研究配置(configure_study)、求解(solve)。这些操作无法满足所有场景。

用户需求：{plan.user_input[:500]}
最后一次错误摘要：{err_summary[:800]}
已执行步骤：{steps_desc}
迭代次数：{iteration_count}

请根据上述失败原因与已尝试的操作，简要列出建议集成的 COMSOL Java API 接口（例如：删除或重命名材料节点、查询模型中已有材料/物理场名称、在已有材料上更新属性等），便于后续开发扩展。每条一行，简洁具体。若无法推断可回答：暂无明确建议。"""
            out = self.llm.call(prompt, temperature=0.1)
            out = (out or "").strip()
            if out and "暂无明确建议" not in out:
                return out[:1500]
        except Exception as e:
            logger.warning("生成集成建议失败: %s", e)
        return None
