"""迭代控制器"""

import json
import re
from typing import TYPE_CHECKING, Literal, Optional

from agent.skills import get_skill_injector
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.schemas.task import ExecutionStep, IterationRecord, Observation, ReActTaskPlan

if TYPE_CHECKING:
    from agent.agents.analysis_agent import AnalysisAgent
    from agent.react.error_collector import ErrorCollector

logger = get_logger(__name__)

# 同一错误指纹重复出现达此次数即视为无效迭代（兜底）
SAME_ERROR_REPEAT_THRESHOLD = 2
# 同一错误「类」累计出现上限（含本次）；超过则熔断，避免 study↔solve 空转
MAX_SAME_ERROR_CLASS = 3
# 同一「错误类 + 修复签名」最多应用次数；再走同一修复直接跳过
SAME_FIX_REPEAT_THRESHOLD = 1
# 错误信息前缀：表示建议 ReActAgent 调用 PlannerOrchestrator 重新编排并告知用户
REORCHESTRATE_PREFIX = "[REORCHESTRATE] "

# 求解不收敛：重建 study 几乎无效，需单独 playbook
_NONCONVERGENCE_RE = re.compile(
    r"不收敛|找不到解|相对残差|没有返回所有参数步长|returned solution is not|relative residual",
    re.IGNORECASE,
)

# 错误归因规则：消息片段 -> 规划层 Agent 类型
# 注意：不收敛类不要归因到 study（否则会反复 configure_study 空转）
_ERROR_ATTRIBUTION = [
    (r"未定义.*材料属性|材料属性.*未定义|固体\s*\d*.*所需的材料属性|所需.*材料属性\s*[kK]|缺.*k\s*", "material"),
    (r"泊松比|杨氏模量|young|poisson|nu\s*[=:]|E\s*[=:]", "material"),
    (r"物理场|边界条件|boundary|physics", "physics"),
    (r"几何|无效.*几何|geometry|invalid\.geom", "geometry"),
    # study 仅覆盖研究配置本身失败，不含「求解不收敛」
    (r"研究配置失败|study.*config|参数化扫描.*无效|parametric.*invalid", "study"),
]


class IterationController:
    """迭代控制器 - 控制迭代流程"""

    def __init__(
        self,
        llm: LLMClient,
        error_collector: Optional["ErrorCollector"] = None,
        analysis_agent: Optional["AnalysisAgent"] = None,
    ):
        """
        初始化迭代控制器

        Args:
            llm: LLM 客户端
            error_collector: 错误收集器，用于在尝试所有路径后请求分析
            analysis_agent: 多方查阅、多角度修复的分析 Agent（可选，懒创建）
        """
        self.llm = llm
        self.error_collector = error_collector
        self._analysis_agent = analysis_agent
        self.last_adjust_summary: str = ""
        self.last_analysis_report = None
        # 本轮 run 内的熔断计数：error_class -> count；"class|fix" -> count
        self._error_class_counts: dict[str, int] = {}
        self._fix_counts: dict[str, int] = {}

    def _get_analysis_agent(self) -> "AnalysisAgent":
        if self._analysis_agent is None:
            from agent.agents.analysis_agent import AnalysisAgent

            self._analysis_agent = AnalysisAgent(llm=self.llm)
        return self._analysis_agent

    @staticmethod
    def _error_class_fingerprint(observation: Observation) -> str:
        """稳定错误类指纹（不依赖 step_id / 动态数字），用于熔断。"""
        msg = (observation.message or "").strip()
        msg = re.sub(r"\s+", " ", msg)
        if _NONCONVERGENCE_RE.search(msg):
            return "solver_nonconvergence"
        if re.search(r"材料属性|未定义.*材料|young|poisson|\bnu\b|\bk\b", msg, re.I):
            return "missing_material_property"
        if re.search(r"边界|物理场|feature|特征遇到问题", msg, re.I):
            return "physics_or_feature"
        if re.search(r"网格|mesh", msg, re.I):
            return "mesh"
        # 去掉残差数值等波动，保留语义骨架
        msg = re.sub(r"\d+\.?\d*", "#", msg)
        return msg[:180] or "unknown_error"

    def _bump_error_class(self, error_class: str) -> int:
        n = self._error_class_counts.get(error_class, 0) + 1
        self._error_class_counts[error_class] = n
        return n

    def _fix_key(self, error_class: str, fix_sig: str) -> str:
        return f"{error_class}|{fix_sig}"

    def _fix_exhausted(self, error_class: str, fix_sig: str) -> bool:
        return self._fix_counts.get(self._fix_key(error_class, fix_sig), 0) >= SAME_FIX_REPEAT_THRESHOLD

    def _record_fix(self, error_class: str, fix_sig: str) -> None:
        key = self._fix_key(error_class, fix_sig)
        self._fix_counts[key] = self._fix_counts.get(key, 0) + 1
        logger.info(
            "记录修复尝试 class=%s fix=%s count=%s",
            error_class,
            fix_sig,
            self._fix_counts[key],
        )

    def _fail_reorchestrate(self, plan: ReActTaskPlan, reason: str) -> ReActTaskPlan:
        plan.status = "failed"
        plan.error = REORCHESTRATE_PREFIX + reason
        self.last_adjust_summary = reason
        logger.warning("熔断并建议重新编排: %s", reason[:200])
        return plan

    def should_iterate(self, plan: ReActTaskPlan, observation: Observation) -> bool:
        """
        判断是否需要迭代（无最大调整次数上限；以最终可求解为目标持续调整，
        仅在步骤全部完成或控制器判定致命/无效迭代时停止）。
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

        return False

    @staticmethod
    def _observation_fingerprint(observation: Observation) -> str:
        """用于同一错误判定的指纹：用错误类，避免 step_id 变化导致永远对不上。"""
        return IterationController._error_class_fingerprint(observation)

    def _is_same_error_repeated(
        self, plan: ReActTaskPlan, observation: Observation, n: int = SAME_ERROR_REPEAT_THRESHOLD
    ) -> bool:
        """同一错误类在最近观察中重复出现则视为无效迭代。"""
        fp = self._observation_fingerprint(observation)
        recent = [obs for obs in plan.observations[-(n + 8) :] if obs.status == "error"]
        count = sum(1 for obs in recent if self._observation_fingerprint(obs) == fp)
        return count >= n

    @staticmethod
    def _attribute_error_to_agent(observation: Observation) -> Optional[Literal["geometry", "material", "physics", "study"]]:
        """根据错误消息将错误归因到规划层 Agent。"""
        msg = observation.message or ""
        if _NONCONVERGENCE_RE.search(msg):
            return None
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
        self.last_adjust_summary = (
            f"错误归因到 {agent_type}，已回退到第 {target_index + 1} 步并准备重跑后续流程。"
            f"观察依据：{(observation.message or '')[:180]}"
        )
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
        self.last_adjust_summary = ""

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
        error_class = self._error_class_fingerprint(observation)
        class_count = self._bump_error_class(error_class)

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

        # 熔断：同一错误类反复出现（例如 study↔solve 空转 39 次）
        if class_count > MAX_SAME_ERROR_CLASS:
            return self._fail_reorchestrate(
                plan,
                f"同一类错误「{error_class}」已连续出现 {class_count} 次且修复未改善，"
                f"停止空转。最近错误: {(observation.message or '')[:180]}",
            )

        current_result = current_step.result if isinstance(current_step.result, dict) else {}
        if current_result.get("needs_planning_clarification"):
            reason = str(
                current_result.get("message") or observation.message or "需要回到规划阶段澄清"
            ).strip()
            return self._fail_reorchestrate(
                plan,
                f"当前步骤需要回到规划阶段补充信息。原因: {reason[:200]}",
            )

        # 专门处理「模型文件被占用」
        if "模型文件被占用" in (observation.message or "") or "无法保存到" in (observation.message or ""):
            fix_sig = "save_to_new_path"
            if self._fix_exhausted(error_class, fix_sig):
                return self._fail_reorchestrate(plan, "模型文件占用问题重复出现，已停止重试。")
            current_step.parameters["save_to_new_path"] = True
            current_step.status = "pending"
            current_step.result = None
            self._record_fix(error_class, fix_sig)
            self.last_adjust_summary = (
                "检测到模型文件被占用，改为保存到新路径后重试当前步骤。"
            )
            logger.info("检测到文件占用错误，已标记保存到新路径并重新执行步骤: %s", current_step.step_id)
            return plan

        # 求解不收敛：禁止「仅重建 study」空转，走专用 playbook
        if error_class == "solver_nonconvergence" or _NONCONVERGENCE_RE.search(
            observation.message or ""
        ):
            handled = self._handle_solver_nonconvergence(plan, observation, feedback, error_class)
            if handled is not None:
                return handled

        # 路径 1：错误归因到规划层 Agent，回退到该步并修复（同修复签名只允许一次）
        attributed = self._attribute_error_to_agent(observation)
        if attributed:
            fix_sig = f"rollback:{attributed}"
            if self._fix_exhausted(error_class, fix_sig):
                logger.warning(
                    "跳过重复归因回退 class=%s fix=%s，改走其他路径",
                    error_class,
                    fix_sig,
                )
            else:
                try:
                    rolled = self._rollback_to_agent(plan, attributed, observation, feedback)
                    if rolled is not None:
                        self._record_fix(error_class, fix_sig)
                        return rolled
                except Exception as e:
                    logger.warning("归因回退失败，继续其他路径: %s", e)

        # 路径 1.5：缺材料属性时优先注入「仅更新属性」步骤，避免整树回退
        step_type = current_step.step_type
        is_solve_or_study_error = step_type in ("solve", "study", "mesh", "physics")
        raw_msg = observation.message or ""
        suggests_material_fix = "材料属性" in raw_msg or (
            "未定义" in raw_msg and "材料" in raw_msg
        )
        suggests_missing_elastic = suggests_material_fix and (
            "nu" in msg
            or "泊松" in raw_msg
            or "poissonsratio" in msg
            or "杨氏" in raw_msg
            or "youngsmodulus" in msg
            or bool(re.search(r'材料属性\s*["\']e["\']', raw_msg, re.I))
            or "线弹性" in raw_msg
        )
        suggests_missing_k = suggests_material_fix and (
            ("k" in msg and "nu" not in msg)
            or "导热" in raw_msg
            or bool(re.search(r"固体\s*\d*.*材料属性.*[kK]|[kK].*材料属性", raw_msg))
        )
        if is_solve_or_study_error and suggests_missing_elastic:
            try:
                injected = self._inject_update_material_elastic(plan, observation)
                if injected is not None:
                    return injected
            except Exception as e:
                logger.warning("注入 update_material_property（E/nu）失败，走回退或重试: %s", e)
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

        # 路径 2：分析 Agent — 多方查阅资料，换角度尝试修复上一轮错误
        try:
            applied = self._try_analysis_fix(plan, observation, error_class)
            if applied is not None:
                return applied
        except Exception as e:
            logger.warning("AnalysisAgent 失败，继续其他路径: %s", e)

        # 同一错误重复且分析 Agent 已无新角度 -> 建议重新编排
        if self._is_same_error_repeated(plan, observation):
            return self._fail_reorchestrate(
                plan,
                "同一错误已重复出现且多角度修复均未奏效，建议重新编排任务。原因: "
                + (observation.message or "")[:200],
            )

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

    def _try_analysis_fix(
        self,
        plan: ReActTaskPlan,
        observation: Observation,
        error_class: str,
        *,
        summary_prefix: str = "",
    ) -> Optional[ReActTaskPlan]:
        """先 analyze 选定角度，若该修复签名未用尽再 apply，避免空转污染计划。"""
        analysis_agent = self._get_analysis_agent()
        report = analysis_agent.analyze(plan, observation)
        self.last_analysis_report = report
        hyp = report.selected() if report else None
        if not hyp:
            logger.info("AnalysisAgent: 无剩余可尝试角度")
            return None
        fix_sig = f"analysis:{hyp.id}"
        if self._fix_exhausted(error_class, fix_sig):
            logger.warning("分析角度 %s 已用过，跳过", hyp.id)
            return None
        applied = analysis_agent.apply(plan, hyp)
        if applied is None:
            return None
        self._record_fix(error_class, fix_sig)
        angles = (
            "；".join(
                f"{h.title}({h.confidence:.0%})"
                for h in (report.hypotheses if report else [])[:3]
            )
            or ""
        )
        self.last_adjust_summary = (
            f"{summary_prefix}分析 Agent 换角度修复：{hyp.title}。"
            f" 查阅资料 {len(report.evidence) if report else 0} 条"
            f"（skill/文档/案例/规则）。候选：{angles}"
        )
        logger.info("AnalysisAgent 已应用修复角度: %s", hyp.id)
        return applied

    def _handle_solver_nonconvergence(
        self,
        plan: ReActTaskPlan,
        observation: Observation,
        feedback: str,
        error_class: str,
    ) -> Optional[ReActTaskPlan]:
        """
        求解不收敛 playbook：
        1) 简化参数化扫描（单点稳态）——禁止只重建相同 study
        2) 回退物理场（相对残差>>1 多为对流/热通量未挂上）
        3) 分析 Agent 换角度（边界/载荷/网格）
        4) 熔断重新编排
        """
        # 步 1：简化参数化 / 稳态设置后重跑 study+solve
        fix_simplify = "simplify_parametric_study"
        if not self._fix_exhausted(error_class, fix_simplify):
            simplified = self._inject_simplify_parametric_study(plan, observation)
            if simplified is not None:
                self._record_fix(error_class, fix_simplify)
                return simplified

        # 步 2：回退物理场（相对残差过大优先查边界，勿先空转 mesh/study）
        fix_physics = "rollback:physics"
        if not self._fix_exhausted(error_class, fix_physics):
            try:
                rolled = self._rollback_to_agent(plan, "physics", observation, feedback)
                if rolled is not None:
                    self._record_fix(error_class, fix_physics)
                    # 注入明确边界修复提示，避免再生成 selection="all" 却未生效的计划
                    for step in rolled.execution_path:
                        if step.step_type == "physics" or step.action == "add_physics":
                            hint = (
                                "求解相对残差过大/找不到解：请核对传热边界——"
                                "底面 HeatFlux(q0) 用具体面 ID；外表面 ConvectiveHeatFlux"
                                "必须真正施加（selection=all 或外表面面列表，参数 h 与 Text）；"
                                "禁止只重建研究；热通量面不要被后续边界完全覆盖。"
                            )
                            prev = str(step.parameters.get("physics_input") or "").strip()
                            step.parameters["physics_input"] = (
                                f"{prev}\n{hint}".strip() if prev else hint
                            )
                            break
                    self.last_adjust_summary = (
                        "求解不收敛：回退物理场检查热通量/对流边界后重试，避免重复重建研究。"
                    )
                    return rolled
            except Exception as e:
                logger.warning("不收敛 playbook 回退物理场失败: %s", e)

        # 步 3：分析 Agent（排除已尝试角度）
        try:
            applied = self._try_analysis_fix(
                plan,
                observation,
                error_class,
                summary_prefix="求解不收敛：",
            )
            if applied is not None:
                return applied
        except Exception as e:
            logger.warning("不收敛 playbook 中 AnalysisAgent 失败: %s", e)

        return self._fail_reorchestrate(
            plan,
            "求解反复不收敛（相对残差过大/参数步未返回），已尝试简化扫描、回退物理场与换角度修复仍失败。"
            f" 原始错误: {(observation.message or '')[:180]}",
        )

    def _inject_simplify_parametric_study(
        self, plan: ReActTaskPlan, observation: Observation
    ) -> Optional[ReActTaskPlan]:
        """将研究步改为「单点稳态、缩短/取消参数扫描」，再重跑 study+solve。"""
        study_index = None
        for i, step in enumerate(plan.execution_path):
            if step.step_type == "study" or step.action == "configure_study":
                study_index = i
                break
        if study_index is None:
            return None

        study_step = plan.execution_path[study_index]
        simplify_hint = (
            "求解出现不收敛/参数步未返回。请改为可收敛的单点稳态研究："
            "暂时取消参数化扫描或仅保留 1 个参数取值；保持固体传热；"
            "不要新建多余研究节点，优先更新现有稳态研究；"
            "确认热通量与对流边界完整后再求解。"
        )
        prev = str(study_step.parameters.get("study_input") or "").strip()
        study_step.parameters["study_input"] = (
            f"{prev}\n{simplify_hint}".strip() if prev else simplify_hint
        )
        study_step.parameters["simplify_for_convergence"] = True
        for i in range(study_index, len(plan.execution_path)):
            plan.execution_path[i].status = "pending"
            plan.execution_path[i].result = None
        plan.current_step_index = study_index
        self.last_adjust_summary = (
            "求解不收敛：将研究简化为单点稳态（缩短参数化扫描）后重试，避免重复空跑。"
            f" 观察：{(observation.message or '')[:120]}"
        )
        logger.info("已注入简化参数化研究指令，回退到 study 步 %s", study_index + 1)
        return plan

    def _material_names_from_plan(self, plan: ReActTaskPlan) -> list:
        material_names = []
        if getattr(plan, "material_plan", None):
            materials = getattr(plan.material_plan, "materials", None) or []
            for m in materials:
                n = getattr(m, "name", None) or getattr(m, "label", None)
                if n:
                    material_names.append(n)
        return material_names

    def _inject_update_material_k(
        self, plan: ReActTaskPlan, observation: Observation
    ) -> Optional[ReActTaskPlan]:
        """当错误为「固体所需材料属性 k 未定义」时，在当前失败步前插入「仅更新已有材料 k」步骤。"""
        idx = plan.current_step_index
        if idx < 0 or idx >= len(plan.execution_path):
            return None
        material_names = self._material_names_from_plan(plan)
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
        self.last_adjust_summary = "检测到缺导热系数 k，已注入补齐材料属性步骤。"
        logger.info(
            "已注入步骤 update_material_property（补 k），下一步将执行该步骤后继续求解"
        )
        return plan

    def _inject_update_material_elastic(
        self, plan: ReActTaskPlan, observation: Observation
    ) -> Optional[ReActTaskPlan]:
        """缺线弹性 nu/E 时，注入仅更新材料弹性属性的步骤。"""
        from agent.executor.java_api_controller import (
            DEFAULT_POISSONS_RATIO,
            DEFAULT_YOUNGS_MODULUS_SOLID,
        )

        idx = plan.current_step_index
        if idx < 0 or idx >= len(plan.execution_path):
            return None
        # 避免重复注入同一修复步
        for step in plan.execution_path:
            if getattr(step, "step_id", "") == "step_fix_material_elastic":
                return None
        material_names = self._material_names_from_plan(plan)
        fix_step = ExecutionStep(
            step_id="step_fix_material_elastic",
            step_type="material",
            action="update_material_property",
            parameters={
                "properties": {
                    "E": DEFAULT_YOUNGS_MODULUS_SOLID,
                    "nu": DEFAULT_POISSONS_RATIO,
                    "youngsmodulus": DEFAULT_YOUNGS_MODULUS_SOLID,
                    "poissonsratio": DEFAULT_POISSONS_RATIO,
                },
                "material_names": material_names if material_names else None,
                "property_group": "Def",
            },
            status="pending",
        )
        plan.execution_path.insert(idx, fix_step)
        plan.execution_path[idx + 1].status = "pending"
        plan.execution_path[idx + 1].result = None
        self.last_adjust_summary = (
            "检测到线弹性缺 nu/E，已注入补齐杨氏模量与泊松比步骤（默认钢：E=200e9 Pa, nu=0.3）。"
        )
        logger.info(
            "已注入步骤 update_material_property（补 E/nu），下一步将执行该步骤后继续求解"
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

唯一使命：无论遇到什么障碍，都必须想办法闭环——产出可求解、可计算的 COMSOL 模型；缺属性就补齐，特征 ID 错误就改成官方可用特征，宁可简化也要算通。

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

                summary = str(suggestions.get("suggested_changes") or "").strip()
                if summary:
                    self.last_adjust_summary = summary
                logger.info("计划已根据错误信息更新: %s", summary)

        except Exception as e:
            logger.warning(f"LLM 改进计划失败: {e}")

        return plan
