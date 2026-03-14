"""任务数据结构定义"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator  # type: ignore[import-not-found]

from schemas.geometry import GeometryPlan
from schemas.material import MaterialPlan
from schemas.mesh import MeshPlan
from schemas.physics import PhysicsPlan
from schemas.study import StudyPlan


class ExecutionStep(BaseModel):
    """执行步骤"""

    step_id: str = Field(..., description="步骤ID")
    step_type: Literal[
        "geometry",
        "material",
        "physics",
        "mesh",
        "study",
        "solve",
        "selection",
        "geometry_io",
        "postprocess",
    ] = Field(..., description="步骤类型")
    action: str = Field(..., description="执行动作")
    parameters: Dict[str, Any] = Field(default={}, description="步骤参数")
    status: Literal["pending", "running", "warning", "completed", "failed", "skipped"] = Field(
        default="pending", description="步骤状态"
    )
    result: Optional[Dict[str, Any]] = Field(default=None, description="执行结果")


class ReasoningCheckpoint(BaseModel):
    """推理检查点"""

    checkpoint_id: str = Field(..., description="检查点ID")
    checkpoint_type: Literal["validation", "verification", "optimization"] = Field(
        ..., description="检查点类型"
    )
    description: str = Field(..., description="检查点描述")
    criteria: Dict[str, Any] = Field(default={}, description="检查标准")
    status: Literal["pending", "passed", "failed"] = Field(
        default="pending", description="检查状态"
    )
    feedback: Optional[str] = Field(default=None, description="检查反馈")


class Observation(BaseModel):
    """观察结果"""

    observation_id: str = Field(..., description="观察ID")
    step_id: str = Field(..., description="关联的步骤ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="观察时间")
    status: Literal["success", "warning", "error"] = Field(..., description="观察状态")
    message: str = Field(..., description="观察消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="观察数据")


class IterationRecord(BaseModel):
    """调整记录（根据执行结果调整计划并继续）"""

    iteration_id: int = Field(..., description="调整轮次")
    timestamp: datetime = Field(default_factory=datetime.now, description="调整时间")
    reason: str = Field(..., description="调整原因")
    changes: Dict[str, Any] = Field(default={}, description="计划变更")
    observations: List[Observation] = Field(default=[], description="本轮的观察结果")


class ErrorAnalysisResult(BaseModel):
    """错误收集器分析结果，供 IterationController 使用"""

    error_type: str = Field(..., description="错误类型归纳")
    suggested_agent: Optional[Literal["geometry", "material", "physics", "study"]] = Field(
        default=None, description="建议负责修复的规划层 Agent"
    )
    suggested_rollback_step_id: Optional[str] = Field(
        default=None, description="建议回退到的步骤 ID"
    )
    suggested_reason: Optional[str] = Field(default=None, description="简短原因说明")
    suggest_reorchestrate: bool = Field(
        default=False, description="是否建议上报 PlannerOrchestrator 重新编排"
    )
    raw_message: Optional[str] = Field(default=None, description="原始错误摘要")


class ClarifyingOption(BaseModel):
    """澄清问题的单个选项"""

    id: str = Field(..., description="选项 ID（前后端通信用，不含空格）")
    label: str = Field(..., description="展示给用户的标签文本")
    value: str = Field(..., description="该选项对应的语义值（用于注入 Prompt）")
    recommended: bool = Field(default=False, description="是否为推荐选项（前端可展示「推荐」标识）")


class ClarifyingQuestion(BaseModel):
    """Plan 阶段用于消解歧义的澄清问题"""

    id: str = Field(..., description="问题 ID（前后端通信用，不含空格）")
    text: str = Field(..., description="提问文案")
    type: Literal["single", "multi"] = Field(
        "single", description="问题类型：单选(single) 或多选(multi)"
    )
    options: List[ClarifyingOption] = Field(default_factory=list, description="候选选项列表")

    @model_validator(mode="after")
    def ensure_supplement_option(self) -> "ClarifyingQuestion":
        """
        在 schema 层强制每个澄清问题都包含“补充选项”。
        若调用方未提供，则自动追加：
        id=opt_supplement, label=其他（请补充）, value=supplement
        """
        supplement_id = "opt_supplement"
        has_supplement = any((opt.id or "").strip() == supplement_id for opt in self.options)
        if not has_supplement:
            self.options.append(
                ClarifyingOption(
                    id=supplement_id,
                    label="其他（请补充）",
                    value="supplement",
                )
            )
        return self


class ClarifyingAnswer(BaseModel):
    """用户对澄清问题的回答（仅用于 Prompt 注入与日志记录）"""

    question_id: str = Field(..., description="对应的 ClarifyingQuestion.id")
    selected_option_ids: List[str] = Field(
        default_factory=list, description="用户选择的选项 ID 列表"
    )


class TaskPlan(BaseModel):
    """完整任务计划"""

    geometry: Optional[GeometryPlan] = Field(default=None, description="几何建模计划")
    material: Optional[MaterialPlan] = Field(default=None, description="材料计划")
    physics: Optional[PhysicsPlan] = Field(default=None, description="物理场计划")
    mesh: Optional[MeshPlan] = Field(default=None, description="网格划分计划")
    study: Optional[StudyPlan] = Field(default=None, description="研究计划")

    def has_geometry(self) -> bool:
        return self.geometry is not None

    def has_material(self) -> bool:
        return self.material is not None

    def has_physics(self) -> bool:
        return self.physics is not None

    def has_mesh(self) -> bool:
        return self.mesh is not None

    def has_study(self) -> bool:
        return self.study is not None


class ReActTaskPlan(BaseModel):
    """ReAct 任务计划 - 包含推理链路和执行链路"""

    task_id: str = Field(..., description="任务ID")
    model_name: str = Field(..., description="模型名称")
    user_input: str = Field(..., description="用户原始输入")

    dimension: int = Field(default=2, description="模型维度（2 或 3）")

    # 执行链路
    execution_path: List[ExecutionStep] = Field(default=[], description="执行步骤列表")
    current_step_index: int = Field(default=0, description="当前执行步骤索引")

    # 推理链路
    reasoning_path: List[ReasoningCheckpoint] = Field(default=[], description="推理检查点列表")

    # 观察结果
    observations: List[Observation] = Field(default=[], description="观察结果列表")

    # 调整历史（根据结果调整计划并继续的轮次记录）
    iterations: List[IterationRecord] = Field(default=[], description="调整历史")

    # 任务状态
    status: Literal["planning", "executing", "observing", "iterating", "completed", "failed"] = (
        Field(default="planning", description="任务状态")
    )

    # 模型路径
    model_path: Optional[str] = Field(default=None, description="生成的模型文件路径")

    # 输出目录（有会话时写入会话 context 目录，模型与操作记录同目录）
    output_dir: Optional[str] = Field(default=None, description="模型与操作记录输出目录")

    # 错误信息
    error: Optional[str] = Field(default=None, description="错误信息")

    # 当因能力不足结束工作流时，建议集成的 COMSOL Java API 接口说明（供展示与后续开发参考）
    integration_suggestions: Optional[str] = Field(
        default=None, description="建议集成的 COMSOL Java API 接口"
    )

    # 具体规划说明（按 COMSOL 流程：几何、材料、物理场、网格、研究、求解等，用于展示与调整时参考）
    plan_description: Optional[str] = Field(
        default=None, description="具体规划说明，非原样复述用户提示词"
    )

    # 在该步骤执行完成后保存 .mph 并结束流程；不填或 solve 表示完整流程。用于「仅几何/仅材料/到网格就停」等场景
    stop_after_step: Optional[str] = Field(
        default=None,
        description="执行到该步骤后保存模型并退出，取值：create_geometry/add_material/add_physics/generate_mesh/configure_study/solve",
    )
    # 规划阶段提给用户的澄清问题（Plan 阶段用）
    clarifying_questions: Optional[List[ClarifyingQuestion]] = Field(
        default=None, description="规划前需要澄清的问题（结构化，供前端展示）"
    )
    # 用户对澄清问题的选择（Clarify 阶段回传，仅用于日志/Prompt 注入）
    clarifying_answers: Optional[List[ClarifyingAnswer]] = Field(
        default=None, description="用户对澄清问题的回答"
    )
    case_library_suggestions: Optional[List[Dict[str, str]]] = Field(
        default=None, description="官方案例库检索结果建议"
    )

    # 子计划（动态属性，由 ActionExecutor 填充）
    geometry_plan: Optional[Any] = None
    material_plan: Optional[Any] = None
    physics_plan: Optional[Any] = None
    mesh_plan: Optional[Any] = None
    study_plan: Optional[Any] = None

    def get_current_step(self) -> Optional[ExecutionStep]:
        if 0 <= self.current_step_index < len(self.execution_path):
            return self.execution_path[self.current_step_index]
        return None

    def add_observation(self, observation: Observation):
        self.observations.append(observation)

    def add_iteration(self, iteration: IterationRecord):
        self.iterations.append(iteration)

    def is_complete(self) -> bool:
        return self.status == "completed"

    def has_failed(self) -> bool:
        return self.status == "failed"
