"""迭代控制器"""

import json
import re
from typing import TYPE_CHECKING, Literal, Optional

from agent.skills import get_skill_injector
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from schemas.task import ExecutionStep, IterationRecord, Observation, ReActTaskPlan

if TYPE_CHECKING:
    from agent.react.error_collector import ErrorCollector

logger = get_logger(__name__)

# 同一错误重复出现达此次数即视为无效迭代，上报编排器重新编排
SAME_ERROR_REPEAT_THRESHOLD = 2
# 错误信息前缀：表示建议 ReActAgent 调用 PlannerOrchestrator 重新编排并告知用户
REORCHESTRATE_PREFIX = "[REORCHESTRATE] "

# 错误归因规则：消息片段 -> 规划层 Agent 类型
_ERROR_ATTRIBUTION = [
    (r"未定义.*材料属性|材料属性.*未定义|固体\s*\d*.*所需的材料属性|所需.*材料属性\s*[kK]|缺.*k\s*", "material"),
    (r"泊松比|杨氏模量|young|poisson|nu\s*[=:]|E\s*[=:]", "material"),
    (r"求解器|稳态|瞬态|不收敛|solver|stationary|time\.dependent|研究.*失败|study.*fail", "study"),
    (r"物理场|边界条件|boundary|physics", "physics"),
    (r"几何|无效.*几何|geometry|invalid\.geom", "geometry"),
]


class IterationController:
    """迭代控制器 - 控制迭代流程"""

    def __init__(self, llm: LLMClient, error_collector: Optional["ErrorCollector"] = None):
        """
        初始化迭代控制器

        Args:
            llm: LLM 客户端
            error_collector: 错误收集器，用于在尝试所有路径后请求分析
        """
        self.llm = llm
        self.error_collector = error_collector
        self.max_iterations = 10

    def should_iterate(self, plan: ReActTaskPlan, observation: Observation) -> bool:
        """
        判断是否需要迭代

        Args:
            plan: 任务计划
            observation: 观察结果

        Returns:
            是否需要迭代
        """
        # 如果观察结果是错误，需要迭代
        if observation.status == "error":
            return True

        # 如果观察结果是警告，可能需要迭代
        if observation.status == "warning":
            # 检查是否有多个警告
            warning_count = sum(1 for obs in plan.observations if obs.status == "warning")
            if warning_count >= 3:
                return True

        # 如果所有步骤都已完成，不需要迭代
        if all(step.status in ("completed", "warning", "skipped") for step in plan.execution_path):
            return False

        # 如果有失败的步骤，需要迭代
        failed_steps = [step for step in plan.execution_path if step.status == "failed"]
        if failed_steps:
            return True

        # 如果迭代次数过多，不再迭代
        if len(plan.iterations) >= self.max_iterations:
            logger.warning("已达到最大调整次数: %s", self.max_iterations)
            return False

        return False

    @staticmethod
    def _observation_fingerprint(observation: Observation) -> str:
        """用于同一错误判定的指纹：规范化 message + step_id。"""
        msg = (observation.message or "").strip()[:300]
        msg = re.sub(r"\s+", " ", msg)
        return f"{observation.step_id}:{msg}"

    def _is_same_error_repeated(
        self, plan: ReActTaskPlan, observation: Observation, n: int = SAME_ERROR_REPEAT_THRESHOLD
    ) -> bool:
        """同一错误（相同指纹）在最近 n 次观察中重复出现则视为无效迭代。"""
        fp = self._observation_fingerprint(observation)
        recent = plan.observations[-(n + 5) :]  # 取最近若干条
        count = sum(1 for obs in recent if self._observation_fingerprint(obs) == fp)
        return count >= n

    @staticmethod
    def _attribute_error_to_agent(observation: Observation) -> Optional[Literal["geometry", "material", "physics", "study"]]:
        """根据错误消息将错误归因到规划层 Agent。"""
        msg = observation.message or ""
        for pattern, agent in _ERROR_ATTRIBUTION:
            if re.search(pattern, msg, re.IGNORECASE):
                return agent  # type: ignore
        return None

    def _rollback_to_agent(
        self,
        plan: ReActTaskPlan,
        agent_type: Literal["geometry", "material", "physics", "study"],
        observation: Observation,
        feedback: str,
    ) -> Optional[ReActTaskPlan]:
        """回退到指定类型 Agent 对应的步骤并可选注入修复参数（材料/物理场用 LLM 生成）。"""
        step_type_map = {
            "geometry": "geometry",
            "material": "material",
            "physics": "physics",
            "study": "study",
        }
        target_type = step_type_map.get(agent_type)
        if not target_type:
            return None
        target_index = None
        for i, step in enumerate(plan.execution_path):
            if step.step_type == target_type:
                target_index = i
                break
        if target_index is None:
            return None
        # 材料/物理场可让 LLM 生成注入参数
        if agent_type in ("material", "physics"):
            rolled = self._rollback_and_inject(plan, observation, feedback)
            if rolled is not None:
                return rolled
        for i in range(target_index, len(plan.execution_path)):
            plan.execution_path[i].status = "pending"
            plan.execution_path[i].result = None
        plan.current_step_index = target_index
        logger.info("已回退到步骤 %s (agent_type=%s)", target_index + 1, agent_type)
        return plan

    def generate_feedback(self, plan: ReActTaskPlan, observation: Observation) -> str:
        """
        生成反馈信息

        Args:
            plan: 任务计划
            observation: 观察结果

        Returns:
            反馈信息
        """
        feedback_parts = []

        # 添加观察结果
        feedback_parts.append(f"观察结果: {observation.message}")

        # 添加当前步骤信息
        current_step = plan.get_current_step()
        if current_step:
            feedback_parts.append(f"当前步骤: {current_step.action} ({current_step.step_type})")
            if current_step.status == "failed":
                feedback_parts.append(f"步骤失败: {current_step.result}")

        # 添加历史观察结果摘要
        recent_observations = plan.observations[-5:]  # 最近5个观察结果
        if recent_observations:
            error_count = sum(1 for obs in recent_observations if obs.status == "error")
            warning_count = sum(1 for obs in recent_observations if obs.status == "warning")
            if error_count > 0:
                feedback_parts.append(f"最近有 {error_count} 个错误")
            if warning_count > 0:
                feedback_parts.append(f"最近有 {warning_count} 个警告")

        # 添加步骤完成情况
        completed = sum(1 for step in plan.execution_path if step.status == "completed")
        total = len(plan.execution_path)
        feedback_parts.append(f"进度: {completed}/{total} 步骤已完成")

        return "\n".join(feedback_parts)

    def update_plan(self, plan: ReActTaskPlan, observation: Observation) -> ReActTaskPlan:
        """
        根据观察结果更新计划

        Args:
            plan: 当前任务计划
            observation: 观察结果

        Returns:
            更新后的计划
        """
        logger.info("更新任务计划...")

        # 生成反馈
        feedback = self.generate_feedback(plan, observation)

        # 记录迭代
        iteration = IterationRecord(
            iteration_id=len(plan.iterations) + 1,
            reason=observation.message,
            changes={},
            observations=[observation],
        )

        # 根据观察结果类型更新计划
        if observation.status == "error":
            plan = self._handle_error(plan, observation, feedback)
        elif observation.status == "warning":
            plan = self._handle_warning(plan, observation, feedback)

        # 添加迭代记录
        plan.add_iteration(iteration)

        return plan

    def _handle_error(
        self, plan: ReActTaskPlan, observation: Observation, feedback: str
    ) -> ReActTaskPlan:
        """
        多路径处理错误：
        1. 归因到规划层 Agent 并单点修复（回退到对应步骤）
        2. 重试 / 局部 LLM 改进
        3. 同一错误重复出现 -> 无效迭代，上报编排器（[REORCHESTRATE]）
        4. 尝试完常规路径后请求 ErrorCollector 分析，按分析结果回退或重新编排
        """
        current_step = plan.get_current_step()
        msg = (observation.message or "").lower()

        # 致命错误：API 或环境问题
        if "object has no attribute" in msg or "has no attribute" in msg:
            plan.status = "failed"
            plan.error = observation.message
            logger.error("致命错误（API/环境），终止: %s", observation.message)
            return plan
        if "cannot find" in msg and ("project root" in msg or "jvm" in msg or "jar" in msg):
            plan.status = "failed"
            plan.error = observation.message
            return plan

        if not current_step:
            logger.warning("无法处理错误：没有当前步骤")
            return plan

        # 路径 3：同一错误多次出现 -> 无效迭代，建议重新编排
        if self._is_same_error_repeated(plan, observation):
            plan.status = "failed"
            plan.error = (
                REORCHESTRATE_PREFIX
                + "同一错误已重复出现，建议重新编排任务并检查建模设置。原因: "
                + (observation.message or "")[:200]
            )
            logger.warning("无效迭代（同一错误重复），建议重新编排: %s", observation.message[:100])
            return plan

        # 专门处理「模型文件被占用」
        if "模型文件被占用" in (observation.message or "") or "无法保存到" in (observation.message or ""):
            current_step.parameters["save_to_new_path"] = True
            current_step.status = "pending"
            current_step.result = None
            logger.info("检测到文件占用错误，已标记保存到新路径并重新执行步骤: %s", current_step.step_id)
            return plan

        # 路径 1：错误归因到规划层 Agent，回退到该步并修复
        attributed = self._attribute_error_to_agent(observation)
        if attributed:
            try:
                rolled = self._rollback_to_agent(plan, attributed, observation, feedback)
                if rolled is not None:
                    return rolled
            except Exception as e:
                logger.warning("归因回退失败，继续其他路径: %s", e)

        # 路径 1.5：若为「固体所需材料属性 k 未定义」类错误，优先注入仅更新材料 k 的步骤，避免整步回退
        step_type = current_step.step_type
        is_solve_or_study_error = step_type in ("solve", "study", "mesh", "physics")
        suggests_material_fix = "材料属性" in (observation.message or "") or (
            "未定义" in msg and "材料" in (observation.message or "")
        )
        suggests_missing_k = suggests_material_fix and (
            "k" in msg or "导热" in msg or bool(re.search(r"固体\s*\d*.*材料属性.*[kK]|[kK].*材料属性", msg))
        )
        if is_solve_or_study_error and suggests_missing_k:
            try:
                injected = self._inject_update_material_k(plan, observation)
                if injected is not None:
                    return injected
            except Exception as e:
                logger.warning("注入 update_material_property 失败，走回退或重试: %s", e)

        suggests_material_or_physics = suggests_material_fix or (
            "所需" in (observation.message or "") and step_type == "solve"
        )
        if is_solve_or_study_error and suggests_material_or_physics:
            try:
                rolled_back_plan = self._rollback_and_inject(plan, observation, feedback)
                if rolled_back_plan is not None:
                    return rolled_back_plan
            except Exception as e:
                logger.warning("回退并注入参数失败，走通用重试: %s", e)

        # 路径 4：已有多轮迭代时，请求 ErrorCollector 分析
        if self.error_collector and len(plan.iterations) >= 1:
            analysis = self.error_collector.analyze(
                observations=plan.observations,
                recent_logs=self.error_collector.get_recent_logs(30),
            )
            if analysis:
                if analysis.suggest_reorchestrate:
                    plan.status = "failed"
                    plan.error = (
                        REORCHESTRATE_PREFIX
                        + (analysis.suggested_reason or "收集器建议重新编排")
                        + " "
                        + (analysis.raw_message or "")[:150]
                    )
                    logger.info("ErrorCollector 建议重新编排")
                    return plan
                if analysis.suggested_agent:
                    try:
                        rolled = self._rollback_to_agent(
                            plan, analysis.suggested_agent, observation, feedback
                        )
                        if rolled is not None:
                            return rolled
                    except Exception as e:
                        logger.warning("按收集器建议回退失败: %s", e)

        # 通用：重试当前步骤或由 LLM 改进计划
        if current_step.status == "failed":
            retry_count = current_step.parameters.get("retry_count", 0)
            if retry_count < 3:
                current_step.status = "pending"
                current_step.parameters["retry_count"] = retry_count + 1
                logger.info("重试步骤 %s (第 %s 次)", current_step.step_id, retry_count + 1)
            else:
                current_step.status = "skipped"
                logger.warning("跳过步骤 %s（重试次数过多）", current_step.step_id)
                if plan.current_step_index < len(plan.execution_path) - 1:
                    plan.current_step_index += 1

        try:
            improved_plan = self._llm_refine_plan(plan, feedback, observation)
            return improved_plan
        except Exception as e:
            logger.warning("LLM 改进计划失败: %s", e)
            return plan

    def _inject_update_material_k(
        self, plan: ReActTaskPlan, observation: Observation
    ) -> Optional[ReActTaskPlan]:
        """当错误为「固体所需材料属性 k 未定义」时，在当前失败步前插入「仅更新已有材料 k」步骤。"""
        idx = plan.current_step_index
        if idx < 0 or idx >= len(plan.execution_path):
            return None
        material_names = []
        if getattr(plan, "material_plan", None):
            materials = getattr(plan.material_plan, "materials", None) or []
            for m in materials:
                n = getattr(m, "name", None) or getattr(m, "label", None)
                if n:
                    material_names.append(n)
        fix_step = ExecutionStep(
            step_id="step_fix_material_k",
            step_type="material",
            action="update_material_property",
            parameters={
                "properties": {"k": 50},
                "material_names": material_names if material_names else None,
                "property_group": "Def",
            },
            status="pending",
        )
        plan.execution_path.insert(idx, fix_step)
        plan.execution_path[idx + 1].status = "pending"
        plan.execution_path[idx + 1].result = None
        logger.info(
            "已注入步骤 update_material_property（补 k），下一步将执行该步骤后继续求解"
        )
        return plan

    def _rollback_and_inject(
        self, plan: ReActTaskPlan, observation: Observation, feedback: str
    ) -> Optional[ReActTaskPlan]:
        """根据错误信息确定应回退的步骤并注入修复参数，然后从该步重新执行。"""
        prompt = f"""
当前 COMSOL 求解/研究失败，错误信息表明可能是前置步骤（材料或物理场）设置不完整。请分析并给出回退步骤与修复参数。

错误信息：
{observation.message}

执行步骤列表（按顺序）：{[(s.step_type, s.action) for s in plan.execution_path]}

请以 JSON 格式返回且仅返回一个 JSON 对象，不要其他文字：
{{
  "rollback_action": "add_material 或 add_physics（需要回退到的步骤）",
  "reason": "简短原因",
  "material_input": "若回退到 add_material，此处写补充材料属性的自然语言描述，例如：为线弹性材料补充泊松比 nu=0.3 和杨氏模量 E",
  "physics_input": "若回退到 add_physics，此处写补充物理场/边界条件的描述；否则可省略"
}}
若无法确定则 rollback_action 设为 "solve"，表示只重试当前步骤。
"""
        # 注入常见 COMSOL 异常处理经验（如重名、缺属性等），供 LLM 采纳
        prompt = get_skill_injector().inject_into_prompt(observation.message or feedback, prompt)
        response = self.llm.call(prompt, temperature=0.1)
        json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
        if not json_match:
            return None
        sug = json.loads(json_match.group(0))
        raw_action = (sug.get("rollback_action") or "").strip().lower()
        rollback_action = raw_action.split(" ")[0].split("（")[0].strip() if raw_action else ""
        if not rollback_action or rollback_action == "solve":
            return None

        # 找到要回退的步骤索引
        target_index = None
        for i, step in enumerate(plan.execution_path):
            if (
                step.action == rollback_action
                or (rollback_action == "add_material" and step.step_type == "material")
                or (rollback_action == "add_physics" and step.step_type == "physics")
            ):
                target_index = i
                break
        if target_index is None:
            return None

        # 将该步及之后所有步骤设为 pending，并注入参数
        for i in range(target_index, len(plan.execution_path)):
            plan.execution_path[i].status = "pending"
            plan.execution_path[i].result = None
            if i == target_index:
                step = plan.execution_path[i]
                if sug.get("material_input") and step.step_type == "material":
                    step.parameters["material_input"] = sug.get("material_input", "")
                if sug.get("physics_input") and step.step_type == "physics":
                    step.parameters["physics_input"] = sug.get("physics_input", "")
        plan.current_step_index = target_index
        logger.info(
            "已回退到步骤 %s (%s)，将重新执行该步及后续步骤",
            target_index + 1,
            plan.execution_path[target_index].action,
        )
        return plan

    def _handle_warning(
        self, plan: ReActTaskPlan, observation: Observation, feedback: str
    ) -> ReActTaskPlan:
        """
        处理警告情况

        Args:
            plan: 任务计划
            observation: 观察结果
            feedback: 反馈信息

        Returns:
            更新后的计划
        """
        # 警告通常不需要立即处理，但可以记录
        logger.info(f"收到警告: {observation.message}")

        # 警告仅在达到阈值时迭代，避免 warning 风暴；阈值以下保持原计划
        warning_count = sum(1 for obs in plan.observations if obs.status == "warning")
        if warning_count < 3:
            return plan

        logger.warning("警告累计达到阈值(%s)，尝试优化计划", warning_count)
        try:
            improved_plan = self._llm_refine_plan(plan, feedback, observation=observation)
            return improved_plan
        except Exception as e:
            logger.warning(f"LLM 优化计划失败: {e}")
            return plan

    def _llm_refine_plan(
        self, plan: ReActTaskPlan, feedback: str, observation: Optional[Observation] = None
    ) -> ReActTaskPlan:
        """
        使用 LLM 根据错误/反馈改进计划：具体说明要修改哪一步、如何修改（按 COMSOL 流程），
        并输出修改后的步骤参数（如 material_input、physics_input 等），而非仅输出提示词。
        """
        try:
            err_msg = (observation.message if observation else "") or feedback
            prompt = f"""
当前 COMSOL 建模任务执行遇到问题，请根据观察到的错误信息重新规划，给出具体、可执行的调整方案（不要只复述用户需求或笼统描述）。

【错误/观察信息】
{err_msg}

【当前计划】
- 模型名称: {plan.model_name}
- 用户原始需求: {plan.user_input}
- 当前步骤: 第 {plan.current_step_index + 1}/{len(plan.execution_path)} 步
- 执行步骤列表: {[s.action for s in plan.execution_path]}

请以 JSON 格式返回且仅返回一个 JSON 对象：
{{
  "suggested_changes": "简短说明本次要做的具体调整（如：在材料步骤为线弹性补充泊松比 nu=0.3 与杨氏模量 E）",
  "skip_current": false,
  "modified_steps": [
    {{ "step_id": "step_2", "parameters": {{ "material_input": "为线弹性材料补充 nu=0.3 和杨氏模量 200e9 Pa" }} }}
  ],
  "new_steps": []
}}

要求：
- modified_steps 中每个元素必须包含 step_id 和 parameters；parameters 里写该步骤需要的具体输入（geometry_input/material_input/physics_input/study_input 等）。
- 根据 COMSOL 流程灵活安排：若缺材料属性就改材料步，若缺边界就改物理场步，若需重算就保持或调整研究/求解。
"""
            prompt = get_skill_injector().inject_into_prompt(feedback, prompt)
            response = self.llm.call(prompt, temperature=0.2)

            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                suggestions = json.loads(json_match.group(0))

                if suggestions.get("skip_current"):
                    current_step = plan.get_current_step()
                    if current_step:
                        current_step.status = "skipped"
                        if plan.current_step_index < len(plan.execution_path) - 1:
                            plan.current_step_index += 1

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

                if "modified_steps" in suggestions:
                    for mod in suggestions["modified_steps"]:
                        step_id = mod.get("step_id")
                        for step in plan.execution_path:
                            if step.step_id == step_id:
                                if "parameters" in mod:
                                    step.parameters.update(mod["parameters"])
                                if "action" in mod:
                                    step.action = mod["action"]
                                step.status = "pending"
                                break

                logger.info("计划已根据错误信息更新: %s", suggestions.get("suggested_changes", ""))

        except Exception as e:
            logger.warning(f"LLM 改进计划失败: {e}")

        return plan
