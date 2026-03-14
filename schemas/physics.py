"""物理场建模数据结构定义"""
from typing import Literal, List, Dict, Any, Union
from pydantic import BaseModel, Field


PhysicsType = Literal[
    "heat", "electromagnetic", "structural", "fluid",
    "acoustics", "piezoelectric", "chemical", "multibody",
]


class BoundaryCondition(BaseModel):
    """边界条件"""

    name: str = Field(..., description="边界条件名称/标签，如 bc1")
    condition_type: str = Field(
        ...,
        description="条件类型 tag，如 Temperature / HeatFlux / FixedConstraint / InletVelocity"
    )
    selection: Union[List[int], str] = Field(
        default="all",
        description="边界选择：边界 ID 列表或 'all'"
    )
    parameters: Dict[str, Any] = Field(
        default={},
        description="条件参数键值对，如 {'T0': 293.15}"
    )


class DomainCondition(BaseModel):
    """域条件"""

    name: str = Field(..., description="域条件名称/标签")
    condition_type: str = Field(
        ...,
        description="条件类型 tag，如 HeatSource / BodyLoad"
    )
    selection: Union[List[int], str] = Field(
        default="all",
        description="域选择：域 ID 列表或 'all'"
    )
    parameters: Dict[str, Any] = Field(
        default={},
        description="条件参数键值对"
    )


class InitialCondition(BaseModel):
    """初始条件"""

    name: str = Field(default="init1", description="初始条件名称")
    variable: str = Field(..., description="变量名，如 T（温度）")
    value: Union[float, str] = Field(..., description="初始值或表达式")


class PhysicsField(BaseModel):
    """物理场定义"""

    type: PhysicsType = Field(..., description="物理场类型")

    parameters: Dict[str, Any] = Field(
        default={},
        description="物理场全局参数"
    )

    boundary_conditions: List[BoundaryCondition] = Field(
        default=[],
        description="边界条件列表"
    )

    domain_conditions: List[DomainCondition] = Field(
        default=[],
        description="域条件列表"
    )

    initial_conditions: List[InitialCondition] = Field(
        default=[],
        description="初始条件列表"
    )


class CouplingDefinition(BaseModel):
    """多物理场耦合定义"""

    type: str = Field(
        ...,
        description="耦合类型，如 thermal_stress / fluid_structure / electromagnetic_heat"
    )
    interfaces: List[str] = Field(
        ...,
        description="参与耦合的物理场接口名称列表"
    )
    parameters: Dict[str, Any] = Field(
        default={},
        description="耦合参数"
    )


class PhysicsPlan(BaseModel):
    """物理场建模计划"""

    fields: list[PhysicsField] = Field(
        default=[],
        description="物理场列表"
    )

    couplings: list[CouplingDefinition] = Field(
        default=[],
        description="多物理场耦合定义列表"
    )
