"""材料数据结构定义"""
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, field_validator


class MaterialProperty(BaseModel):
    """材料属性（单个物理量）"""

    name: str = Field(
        ...,
        description="属性名称，如 thermalconductivity / density / specificheat / youngsmodulus 等"
    )

    value: Union[float, str, List[float]] = Field(
        ...,
        description="属性值：数值、表达式字符串或数组"
    )

    unit: str = Field(
        default="",
        description="单位，如 W/(m*K)、kg/m^3 等（可选，留空时使用 COMSOL 默认单位）"
    )


class MaterialDefinition(BaseModel):
    """材料定义"""

    name: str = Field(..., description="材料标识名（如 mat1）")

    label: str = Field(default="", description="材料显示名（如 Copper、Steel）")

    builtin_name: Optional[str] = Field(
        default=None,
        description="COMSOL 内置材料库名称（如 'Copper', 'Steel AISI 4340'）；"
        "若指定则忽略 properties，直接从材料库加载"
    )

    properties: List[MaterialProperty] = Field(
        default=[],
        description="自定义材料属性列表（builtin_name 为 None 时使用）"
    )

    property_group: str = Field(
        default="Def",
        description="COMSOL 属性组名（通常为 Def）"
    )


class MaterialAssignment(BaseModel):
    """材料分配到几何域"""

    material_name: str = Field(..., description="材料标识名（对应 MaterialDefinition.name）")

    domain_ids: List[int] = Field(
        default=[],
        description="域 ID 列表（如 [1, 2]）；为空且 assign_all=True 时分配到所有域"
    )

    assign_all: bool = Field(
        default=False,
        description="是否分配到所有域"
    )

    @field_validator("domain_ids")
    @classmethod
    def validate_domain_ids(cls, v: List[int], info) -> List[int]:
        assign_all = info.data.get("assign_all", False)
        if not v and not assign_all:
            pass  # 允许空列表——执行时如果也没 assign_all，则跳过分配
        return v


class MaterialPlan(BaseModel):
    """材料计划"""

    materials: List[MaterialDefinition] = Field(
        default=[],
        description="材料定义列表"
    )

    assignments: List[MaterialAssignment] = Field(
        default=[],
        description="材料分配列表"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "materials": [m.model_dump() for m in self.materials],
            "assignments": [a.model_dump() for a in self.assignments],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialPlan":
        return cls(**data)
