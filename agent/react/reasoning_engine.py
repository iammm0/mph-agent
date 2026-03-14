"""推理引擎"""

import json
import re
import traceback
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional
from uuid import uuid4

from agent.core.events import EventBus, EventType
from agent.skills import get_skill_injector
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.utils.prompt_loader import prompt_loader
from schemas.task import ClarifyingAnswer, ExecutionStep, ReActTaskPlan, ReasoningCheckpoint

if TYPE_CHECKING:
    from schemas.task import TaskPlan

logger = get_logger(__name__)

# 用户说「只建几何」「只创建几何」等时，若 LLM 未设定 stop_after_step，用此处推断的步骤截断，避免默认走完整流程
_GEOMETRY_ONLY_PHRASES = (
    "只建几何",
    "只创建几何",
    "仅几何",
    "只画几何",
    "就建几何",
    "建几何就行",
    "只要几何",
)
_MATERIAL_STOP_PHRASES = ("加完材料就行", "只加材料", "材料加完就停", "赋完材料就结束")
_PHYSICS_STOP_PHRASES = ("加完物理场就行", "加完物理场就停", "只加物理场", "物理场加完就结束")
_MESH_STOP_PHRASES = ("划分完网格就停", "划分网格就停", "网格划完就结束", "只划分网格")


def _infer_stop_after_from_user_input(user_input: str) -> Optional[str]:
    """从用户输入推断应在哪一步结束后保存并退出；未识别则返回 None（表示不覆盖 LLM 的 stop_after_step）。"""
    if not (user_input or "").strip():
        return None
    text = (user_input or "").strip()
    if any(p in text for p in _GEOMETRY_ONLY_PHRASES):
        return "create_geometry"
    if any(p in text for p in _MATERIAL_STOP_PHRASES):
        return "add_material"
    if any(p in text for p in _PHYSICS_STOP_PHRASES):
        return "add_physics"
    if any(p in text for p in _MESH_STOP_PHRASES):
        return "generate_mesh"
    return None


def _task_plan_to_execution_path(task_plan: "TaskPlan") -> List[ExecutionStep]:
    """
    从 TaskPlan（编排器产出）转为 ReAct 执行链路。
    严格按 COMSOL 顺序且仅包含指令需要的步骤：几何 → 材料 → 物理场 → 网格 → 研究 → 求解。
    仅当需要物理场或研究时才添加网格/研究/求解（仅几何或几何+材料时只建模型不求解）。
    """
    steps = []
    idx = 0
    if task_plan.geometry:
        idx += 1
        steps.append(
            ExecutionStep(
                step_id=f"step_{idx}",
                step_type="geometry",
                action="create_geometry",
                parameters={"geometry_input": ""},
                status="pending",
            )
        )
    if task_plan.material:
        idx += 1
        steps.append(
            ExecutionStep(
                step_id=f"step_{idx}",
                step_type="material",
                action="add_material",
                parameters={"material_input": ""},
                status="pending",
            )
        )
    if task_plan.physics:
        idx += 1
        steps.append(
            ExecutionStep(
                step_id=f"step_{idx}",
                step_type="physics",
                action="add_physics",
                parameters={"physics_input": ""},
                status="pending",
            )
        )
    # 当有网格计划或需要求解（物理场/研究）时加入网格步；若有 task_plan.mesh 则把规划参数带入
    mesh_plan = getattr(task_plan, "mesh", None)
    need_mesh = bool(mesh_plan or task_plan.physics or getattr(task_plan, "study", None))
    if need_mesh:
        idx += 1
        mesh_params = {}
        if mesh_plan:
            mesh_params = {
                "element_size": getattr(mesh_plan, "element_size", None),
                "sequence": getattr(mesh_plan, "sequence", "free"),
                "quality": getattr(mesh_plan, "quality", "normal"),
                "parameters": getattr(mesh_plan, "parameters", {}),
            }
        steps.append(
            ExecutionStep(
                step_id=f"step_{idx}",
                step_type="mesh",
                action="generate_mesh",
                parameters=mesh_params,
                status="pending",
            )
        )
    need_solve = bool(task_plan.physics or getattr(task_plan, "study", None))
    if need_solve:
        idx += 1
        steps.append(
            ExecutionStep(
                step_id=f"step_{idx}",
                step_type="study",
                action="configure_study",
                parameters={"study_input": ""},
                status="pending",
            )
        )
        idx += 1
        steps.append(
            ExecutionStep(
                step_id=f"step_{idx}",
                step_type="solve",
                action="solve",
                parameters={},
                status="pending",
            )
        )
    return steps


class ReasoningEngine:
    """推理引擎 - 负责推理和规划"""

    def __init__(
        self,
        llm: LLMClient,
        event_bus: Optional[EventBus] = None,
        use_planner_orchestrator: bool = True,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """
        初始化推理引擎

        Args:
            llm: LLM 客户端
            event_bus: 可选事件总线，用于流式输出 LLM 思维过程（LLM_STREAM_CHUNK）
            use_planner_orchestrator: 若为 True，使用 PlannerOrchestrator 将用户提示词拆解为串行任务并调用几何/材料/物理场/研究四个 Agent，再转为 ReAct 计划；否则沿用原有 LLM 单次理解+规划。
            backend/api_key/base_url/ollama_url/model: 传给 PlannerOrchestrator 使用同一套 LLM 配置
        """
        self.llm = llm
        self._event_bus = event_bus
        self._use_planner_orchestrator = use_planner_orchestrator
        self._llm_kwargs = {
            "backend": backend,
            "api_key": api_key,
            "base_url": base_url,
            "ollama_url": ollama_url,
            "model": model,
        }

    def understand_and_plan(
        self,
        user_input: str,
        model_name: str,
        memory_context: Optional[str] = None,
        clarifying_answers: Optional[List[ClarifyingAnswer]] = None,
    ) -> ReActTaskPlan:
        """
        理解用户需求并规划任务

        Args:
            user_input: 用户输入
            model_name: 模型名称
            memory_context: 本会话的摘要记忆（桌面多会话时由记忆 Agent 维护）
        """
        logger.info("理解用户需求并规划任务...")

        if self._use_planner_orchestrator:
            try:
                from agent.planner.orchestrator import PlannerOrchestrator

                kw = {k: v for k, v in self._llm_kwargs.items() if v is not None}
                orchestrator = PlannerOrchestrator(**kw)
                # 将 clarifying_answers 注入到 Planner 层：在已有上下文前追加一段「澄清答案摘要」
                extra_ctx = ""
                if clarifying_answers:
                    try:
                        summary_items = [
                            f"- 问题 {a.question_id}: 选项 {', '.join(a.selected_option_ids) or '（未选择）'}"
                            for a in clarifying_answers
                        ]
                        extra_ctx = "【用户已回答的澄清问题】\n" + "\n".join(summary_items) + "\n\n"
                    except Exception:
                        extra_ctx = ""
                eff_context = (extra_ctx + (memory_context or "")).strip() or None

                task_plan, _, serial_plan = orchestrator.run(user_input, context=eff_context)
                execution_path = _task_plan_to_execution_path(task_plan)
                reasoning_path = self.plan_reasoning_path(execution_path)
                plan_description = (serial_plan.plan_description or "").strip()
                stop_after = execution_path[-1].action if execution_path else None
                plan = ReActTaskPlan(
                    task_id=str(uuid4()),
                    model_name=model_name,
                    user_input=user_input,
                    execution_path=execution_path,
                    reasoning_path=reasoning_path,
                    status="planning",
                    plan_description=plan_description.strip() or None,
                    stop_after_step=stop_after,
                )
                plan.geometry_plan = task_plan.geometry
                plan.material_plan = task_plan.material
                plan.physics_plan = getattr(task_plan, "physics", None)
                plan.mesh_plan = getattr(task_plan, "mesh", None)
                plan.study_plan = getattr(task_plan, "study", None)
                # 首次调用：Planner 可能会给出 clarifying_questions；二次调用（带 clarifying_answers）时按约定应为空
                serial_cq = getattr(serial_plan, "clarifying_questions", None)
                if clarifying_answers:
                    if serial_cq:
                        logger.warning(
                            "二次调用带 clarifying_answers 仍返回 clarifying_questions，已忽略"
                        )
                    plan.clarifying_questions = None
                    plan.clarifying_answers = clarifying_answers
                else:
                    plan.clarifying_questions = serial_cq
                    plan.clarifying_answers = None
                plan.case_library_suggestions = getattr(
                    serial_plan, "case_library_suggestions", None
                )
                logger.info("规划完成（编排器）: {} 个执行步骤", len(execution_path))
                return plan
            except Exception as e:
                logger.error(
                    "Planner 编排器执行失败，回退到 LLM 单次规划: %s\n%s",
                    e,
                    traceback.format_exc(),
                )

        # 使用 LLM 理解需求（可注入记忆上下文）
        understanding = self.understand_requirement(user_input, memory_context=memory_context)

        # 若用户明确说了「只建几何」「只创建几何」等，但 LLM 未设定 stop_after_step，则按用户措辞截断，避免默认走完整流程
        inferred_stop = _infer_stop_after_from_user_input(user_input)
        if inferred_stop is not None:
            current = (understanding.get("stop_after_step") or "solve").strip().lower()
            if not current or current == "solve":
                understanding["stop_after_step"] = inferred_stop
                logger.info("根据用户措辞推断停止步: {}", inferred_stop)

        # 规划执行链路（每个步骤带具体参数，而非原样复述用户提示词）
        execution_path = self.plan_execution_path(understanding)

        # 规划推理链路
        reasoning_path = self.plan_reasoning_path(execution_path)

        # 具体规划说明（用于展示）
        plan_description = (
            understanding.get("plan_description") or understanding.get("reasoning") or ""
        )
        stop_after_step = understanding.get("stop_after_step") or "solve"

        # 创建任务计划
        plan = ReActTaskPlan(
            task_id=str(uuid4()),
            model_name=model_name,
            user_input=user_input,
            execution_path=execution_path,
            reasoning_path=reasoning_path,
            status="planning",
            plan_description=plan_description.strip() or None,
            stop_after_step=stop_after_step if stop_after_step != "solve" else None,
        )
        plan.clarifying_questions = understanding.get("clarifying_questions")
        plan.case_library_suggestions = understanding.get("case_library_suggestions")

        logger.info(f"规划完成: {len(execution_path)} 个执行步骤, {len(reasoning_path)} 个检查点")

        return plan

    def understand_requirement(
        self, user_input: str, memory_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        理解用户需求

        Args:
            user_input: 用户输入
            memory_context: 本会话的摘要记忆（可选）
        """
        try:
            prompt = prompt_loader.format(
                "react",
                "reasoning",
                user_input=user_input,
                memory_context=(memory_context or "（无）").strip(),
            )
        except Exception:
            # 如果 Prompt 不存在，使用简单模板
            prompt = f"""
请分析以下 COMSOL 建模需求，识别需要哪些建模步骤：

用户需求：{user_input}

请以 JSON 格式返回分析结果，包含：
- task_type: 任务类型（geometry/physics/study/full）
- required_steps: 需要的步骤列表
- parameters: 关键参数
"""
        prompt = get_skill_injector().inject_into_prompt(user_input, prompt)
        if self._event_bus:

            def on_chunk(chunk: str) -> None:
                if chunk and self._event_bus is not None:
                    self._event_bus.emit_type(
                        EventType.LLM_STREAM_CHUNK, {"phase": "planning", "chunk": chunk}
                    )

            stream_callback: Callable[[str], None] = on_chunk

            try:
                response = self.llm.call_stream(prompt, temperature=0.1, on_chunk=stream_callback)
            except Exception:
                response = self.llm.call(prompt, temperature=0.1)
        else:
            response = self.llm.call(prompt, temperature=0.1)

        # 提取 JSON
        understanding = self._extract_json(response)

        return understanding

    def plan_execution_path(self, understanding: Dict[str, Any]) -> List[ExecutionStep]:
        """
        规划执行链路，每个步骤携带该步的具体参数（geometry_input / material_input / physics_input 等），
        按 COMSOL 建模流程灵活安排，而非原样复述用户提示词。
        """
        steps = []

        task_type = understanding.get("task_type", "full")
        required_steps = understanding.get("required_steps", [])
        params = understanding.get("parameters") or {}
        stop_after_step = understanding.get("stop_after_step") or "solve"

        if not required_steps:
            if task_type == "geometry":
                required_steps = ["create_geometry"]
            elif task_type == "physics":
                required_steps = ["create_geometry", "add_material", "add_physics"]
            elif task_type == "study":
                required_steps = [
                    "create_geometry",
                    "add_material",
                    "add_physics",
                    "configure_study",
                ]
            else:
                required_steps = [
                    "create_geometry",
                    "add_material",
                    "add_physics",
                    "generate_mesh",
                    "configure_study",
                    "solve",
                ]

        # 按 stop_after_step 截断：只执行到该步（含）即保存模型并结束
        step_order = [
            "create_geometry",
            "add_material",
            "add_physics",
            "generate_mesh",
            "configure_study",
            "solve",
        ]
        if stop_after_step and stop_after_step in step_order:
            idx = step_order.index(stop_after_step)
            allowed = set(step_order[: idx + 1])
            required_steps = [s for s in required_steps if s not in step_order or s in allowed]

        step_type_map = {
            "create_geometry": "geometry",
            "add_material": "material",
            "update_material_property": "material",
            "add_physics": "physics",
            "generate_mesh": "mesh",
            "configure_study": "study",
            "solve": "solve",
            "import_geometry": "geometry_io",
            "create_selection": "selection",
            "export_results": "postprocess",
            "call_official_api": "java_api",
        }

        # 每步只带该步需要的具体参数
        step_parameters_map = {
            "create_geometry": {"geometry_input": params.get("geometry_input", "")},
            "add_material": {"material_input": params.get("material_input", "")},
            "update_material_property": {
                "material_name": params.get("material_name"),
                "material_names": params.get("material_names"),
                "properties": params.get("properties", {"k": 50}),
                "property_group": params.get("property_group", "Def"),
            },
            "add_physics": {"physics_input": params.get("physics_input", "")},
            "generate_mesh": {"mesh": params.get("mesh", {})},
            "configure_study": {"study_input": params.get("study_input", "")},
            "solve": {},
            "import_geometry": {
                "file_path": params.get("file_path"),
                "geom_tag": params.get("geom_tag", "geom1"),
            },
            "create_selection": {
                "tag": params.get("tag", "sel1"),
                "geom_tag": params.get("geom_tag", "geom1"),
                "entities": params.get("entities"),
                "all": params.get("all"),
            },
            "export_results": {
                "out_path": params.get("out_path"),
                "plot_group_tag": params.get("plot_group_tag"),
                "export_type": params.get("export_type"),
            },
            # 高级：直接调度已集成的官方 Java API
            # - method + args + target_path → invoke_official_api
            # - wrapper/wrapper_name → 调用 api_* 包装函数
            "call_official_api": {
                "method": params.get("method"),
                "wrapper": params.get("wrapper") or params.get("wrapper_name"),
                "args": params.get("args"),
                "target_path": params.get("target_path"),
            },
        }

        for i, step_action in enumerate(required_steps):
            step_type = step_type_map.get(step_action, "geometry")
            step_params = step_parameters_map.get(step_action, {})
            if not step_params and params:
                step_params = {
                    k: v
                    for k, v in params.items()
                    if k
                    in ("geometry_input", "material_input", "physics_input", "mesh", "study_input")
                }
            step = ExecutionStep(
                step_id=f"step_{i + 1}",
                step_type=step_type,
                action=step_action,
                parameters=step_params if step_params else params,
                status="pending",
            )
            steps.append(step)

        return steps

    def plan_reasoning_path(self, execution_path: List[ExecutionStep]) -> List[ReasoningCheckpoint]:
        """
        规划推理链路（验证点、检查点）

        Args:
            execution_path: 执行步骤列表

        Returns:
            推理检查点列表
        """
        checkpoints = []

        # 为每个执行步骤创建检查点
        for step in execution_path:
            checkpoint = ReasoningCheckpoint(
                checkpoint_id=f"checkpoint_{step.step_id}",
                checkpoint_type="validation",
                description=f"验证 {step.action} 步骤",
                criteria={"step_id": step.step_id},
                status="pending",
            )
            checkpoints.append(checkpoint)

        # 添加整体验证检查点
        overall_checkpoint = ReasoningCheckpoint(
            checkpoint_id="checkpoint_overall",
            checkpoint_type="verification",
            description="整体模型验证",
            criteria={"all_steps_complete": True},
            status="pending",
        )
        checkpoints.append(overall_checkpoint)

        return checkpoints

    def reason(self, plan: ReActTaskPlan) -> Dict[str, Any]:
        """
        推理当前状态，决定下一步行动

        Args:
            plan: 当前任务计划

        Returns:
            思考结果
        """
        current_step = plan.get_current_step()

        # 执行链路为空时，不能判定完成（避免 all([]) 为 True 导致假完成）
        if not plan.execution_path:
            return {"action": "replan", "reasoning": "执行路径为空，需要重新规划", "parameters": {}}

        # 如果所有步骤都已完成
        if all(step.status in ("completed", "warning", "skipped") for step in plan.execution_path):
            return {"action": "complete", "reasoning": "所有步骤已完成", "parameters": {}}

        # 如果有失败的步骤，优先让当前失败步骤回到 pending 重试，避免输出无法被 act 消费的控制动作
        failed_steps = [step for step in plan.execution_path if step.status == "failed"]
        if failed_steps:
            target = None
            if current_step and current_step.status == "failed":
                target = current_step
            else:
                target = failed_steps[0]

            target.status = "pending"
            try:
                idx = plan.execution_path.index(target)
                plan.current_step_index = idx
            except ValueError:
                pass

            return {
                "action": target.action,
                "reasoning": f"检测到失败步骤，重试: {target.action}",
                "parameters": target.parameters,
            }

        # 如果有待执行的步骤
        if current_step and current_step.status == "pending":
            return {
                "action": current_step.action,
                "reasoning": f"执行步骤: {current_step.action}",
                "parameters": current_step.parameters,
            }

        # warning 视为可继续（该步已执行但有告警），推进到下一步
        if current_step and current_step.status in ("warning", "completed", "skipped"):
            if plan.current_step_index < len(plan.execution_path) - 1:
                plan.current_step_index += 1
                next_step = plan.get_current_step()
                if next_step:
                    if next_step.status == "failed":
                        next_step.status = "pending"
                    return {
                        "action": next_step.action,
                        "reasoning": f"继续执行下一步: {next_step.action}",
                        "parameters": next_step.parameters,
                    }

        # 默认：继续执行下一步（并跳过已完成/告警/跳过状态的步骤）
        while plan.current_step_index < len(plan.execution_path) - 1:
            plan.current_step_index += 1
            next_step = plan.get_current_step()
            if not next_step:
                break
            if next_step.status in ("completed", "warning", "skipped"):
                continue
            if next_step.status == "failed":
                next_step.status = "pending"
            return {
                "action": next_step.action,
                "reasoning": f"继续执行下一步: {next_step.action}",
                "parameters": next_step.parameters,
            }

        # 兜底：仅当执行链路非空且都处于可完成状态时才返回 complete
        if plan.execution_path and all(
            step.status in ("completed", "warning", "skipped") for step in plan.execution_path
        ):
            return {"action": "complete", "reasoning": "没有更多待执行步骤", "parameters": {}}

        return {"action": "replan", "reasoning": "未找到可执行步骤，需重新规划", "parameters": {}}

    def validate_plan(self, plan: ReActTaskPlan) -> Dict[str, Any]:
        """
        验证计划的合理性和完整性

        Args:
            plan: 任务计划

        Returns:
            验证结果
        """
        errors = []
        warnings = []

        # 检查执行路径
        if not plan.execution_path:
            errors.append("执行路径为空")

        # 检查步骤顺序
        step_types = [step.step_type for step in plan.execution_path]
        if "geometry" not in step_types and ("physics" in step_types or "mesh" in step_types):
            errors.append("几何建模必须在物理场和网格之前")

        if "physics" not in step_types and "study" in step_types:
            warnings.append("研究配置通常需要物理场")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def refine_plan(self, plan: ReActTaskPlan, feedback: str) -> ReActTaskPlan:
        """
        根据反馈改进计划

        Args:
            plan: 当前任务计划
            feedback: 反馈信息

        Returns:
            改进后的计划
        """
        logger.info(f"根据反馈改进计划: {feedback}")

        # 使用 LLM 分析反馈并生成改进建议
        try:
            prompt = f"""
当前任务计划执行遇到问题，请分析反馈并给出改进建议：

任务计划：
{json.dumps(plan.model_dump(), ensure_ascii=False, indent=2)}

反馈信息：
{feedback}

请以 JSON 格式返回改进建议，包含：
- suggested_changes: 建议的变更
- new_steps: 需要添加的新步骤（如果有）
- modified_steps: 需要修改的步骤（如果有）
"""
            prompt = get_skill_injector().inject_into_prompt(feedback, prompt)
            response = self.llm.call(prompt, temperature=0.2)
            suggestions = self._extract_json(response)

            # 应用改进建议
            if "new_steps" in suggestions:
                for step_data in suggestions["new_steps"]:
                    new_step = ExecutionStep(
                        step_id=f"step_{len(plan.execution_path) + 1}",
                        step_type=step_data.get("step_type", "geometry"),
                        action=step_data.get("action", "create_geometry"),
                        parameters=step_data.get("parameters", {}),
                        status="pending",
                    )
                    plan.execution_path.append(new_step)

            # 更新现有步骤
            if "modified_steps" in suggestions:
                for mod in suggestions["modified_steps"]:
                    step_id = mod.get("step_id")
                    for step in plan.execution_path:
                        if step.step_id == step_id:
                            if "parameters" in mod:
                                step.parameters.update(mod["parameters"])
                            break

        except Exception as e:
            logger.warning(f"改进计划失败: {e}")

        return plan

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """从文本中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 代码块
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取第一个 { ... } 块
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # 如果都失败，返回默认值
        logger.warning("无法从响应中提取 JSON，使用默认值")
        return {"task_type": "geometry", "required_steps": ["create_geometry"], "parameters": {}}
