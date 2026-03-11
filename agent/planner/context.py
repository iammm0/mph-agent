"""
Planner 层 A2A 共享上下文与串行计划数据结构。

编排器将用户提示词拆解为串行任务后，按顺序调用几何/材料/物理场/研究四个 Agent。
每个 Agent 执行前后可读写共享上下文，以便在遇到 error/exception 时，
其余 Agent 能获知已完成的修改与错误信息，便于重试或适配。
"""
from typing import Optional, List, Any, Literal, Dict
from pydantic import BaseModel, Field
from datetime import datetime

from schemas.task import ClarifyingQuestion


AgentTypeLiteral = Literal["geometry", "material", "physics", "study"]


class PlannerStepRecord(BaseModel):
    """单步执行记录：供其他 Agent 与编排器查看「谁做了哪些修改、是否出错」。"""

    step_index: int = Field(..., description="步骤序号（从 1 开始）")
    agent_type: AgentTypeLiteral = Field(..., description="执行的 Agent 类型")
    success: bool = Field(..., description="是否成功")
    result_summary: Optional[str] = Field(None, description="结果摘要（供注入到后续 Agent 的 prompt）")
    error: Optional[str] = Field(None, description="错误或异常信息")
    raw_result: Optional[Any] = Field(None, description="原始结果对象引用（如 GeometryPlan），不序列化到 JSON")
    timestamp: datetime = Field(default_factory=datetime.now, description="执行时间")

    model_config = {"arbitrary_types_allowed": True}

    def to_context_line(self) -> str:
        """生成供注入到其他 Agent 上下文的单行描述。"""
        if self.success:
            return f"[步骤{self.step_index}] {self.agent_type}: 成功 — {self.result_summary or '已完成'}"
        return f"[步骤{self.step_index}] {self.agent_type}: 失败 — {self.error or '未知错误'}"


class PlannerSharedContext(BaseModel):
    """
    Planner 层共享上下文（A2A 通信载体）。

    编排器在每步执行后更新 execution_history；各 Agent 的 parse() 可接收
    本上下文，将「已完成步骤与错误」注入到自己的 prompt，从而在遇到
    error/exception 时知道其余 Agent 做了哪些修改。
    """

    user_input: str = Field(default="", description="用户原始输入")
    execution_history: List[PlannerStepRecord] = Field(
        default_factory=list,
        description="已执行步骤记录（按顺序）",
    )
    last_error: Optional[str] = Field(None, description="最近一次错误信息，便于重试时参考")
    model_config = {"arbitrary_types_allowed": True}

    def get_context_for_agent(self, for_agent_type: Optional[AgentTypeLiteral] = None) -> str:
        """
        生成供注入到某 Agent prompt 的「其他 Agent 已完成的修改与错误」摘要。
        for_agent_type 可用来排除当前 Agent 自身的历史（若需要）。
        """
        if not self.execution_history:
            return "（尚无其他 Agent 的修改记录。）"
        lines = []
        for r in self.execution_history:
            if for_agent_type and r.agent_type == for_agent_type:
                continue
            lines.append(r.to_context_line())
        if self.last_error and (not for_agent_type or "error" in (self.last_error or "")):
            lines.append(f"最近错误: {self.last_error}")
        return "\n".join(lines) if lines else "（尚无其他 Agent 的修改记录。）"

    def append_success(
        self,
        step_index: int,
        agent_type: AgentTypeLiteral,
        result_summary: str,
        raw_result: Any = None,
    ) -> None:
        """记录一步成功执行。"""
        self.execution_history.append(
            PlannerStepRecord(
                step_index=step_index,
                agent_type=agent_type,
                success=True,
                result_summary=result_summary,
                raw_result=raw_result,
            )
        )
        self.last_error = None

    def append_failure(
        self,
        step_index: int,
        agent_type: AgentTypeLiteral,
        error: str,
    ) -> None:
        """记录一步失败。"""
        self.execution_history.append(
            PlannerStepRecord(
                step_index=step_index,
                agent_type=agent_type,
                success=False,
                error=error,
            )
        )
        self.last_error = error


class SerialPlanStep(BaseModel):
    """串行计划中的单步：由编排器 LLM 分解用户提示词得到。"""

    step_index: int = Field(..., description="步骤序号（从 1 开始）")
    agent_type: AgentTypeLiteral = Field(..., description="负责执行的 Agent：geometry/material/physics/study")
    description: str = Field(..., description="该步任务描述")
    input_snippet: str = Field(
        default="",
        description="该步对应的用户输入片段或从总需求中抽取的句子",
    )


class SerialPlan(BaseModel):
    """串行计划：用户提示词被编排器拆解后的有序步骤列表。"""

    steps: List[SerialPlanStep] = Field(default_factory=list, description="串行步骤")
    plan_description: Optional[str] = Field(None, description="整体规划说明（可选）")
    # 由 Planner 或后处理构造的澄清问题（结构化）
    clarifying_questions: Optional[List[ClarifyingQuestion]] = Field(
        default=None, description="规划前需要澄清的问题"
    )
    case_library_suggestions: Optional[List[Dict[str, str]]] = Field(
        default=None, description="官方案例库检索结果建议"
    )

    def step_count(self) -> int:
        return len(self.steps)
