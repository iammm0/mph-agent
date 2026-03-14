"""研究类型数据结构定义"""
from typing import Literal, Dict, Any, Optional
from pydantic import BaseModel, Field


StudyTypeEnum = Literal[
    "stationary", "time_dependent", "eigenvalue", "frequency", "parametric",
]


class ParametricSweep(BaseModel):
    """参数化扫描定义"""

    parameter_name: str = Field(..., description="扫描的参数名")
    range_start: float = Field(..., description="起始值")
    range_end: float = Field(..., description="终止值")
    step: Optional[float] = Field(default=None, description="步长（可选，None 时由求解器自动确定）")
    num_points: Optional[int] = Field(default=None, description="采样点数（与 step 二选一）")


class StudyType(BaseModel):
    """研究类型定义"""

    type: StudyTypeEnum = Field(..., description="研究类型")

    parameters: Dict[str, Any] = Field(
        default={},
        description="研究参数（如瞬态的时间范围、频域的频率范围）"
    )

    parametric_sweep: Optional[ParametricSweep] = Field(
        default=None,
        description="参数化扫描配置（可选）"
    )


class StudyPlan(BaseModel):
    """研究计划"""

    studies: list[StudyType] = Field(
        default=[],
        description="研究列表"
    )
