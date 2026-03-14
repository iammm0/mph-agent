"""几何建模数据结构定义 — 支持 2D/3D 形状、布尔运算、拉伸/旋转等操作"""
from typing import Literal, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


# 2D 形状类型
SHAPE_2D = {"rectangle", "circle", "ellipse", "polygon"}
# 3D 形状类型
SHAPE_3D = {"block", "cylinder", "sphere", "cone", "torus"}
# 所有支持的形状类型
ALL_SHAPE_TYPES = SHAPE_2D | SHAPE_3D

ShapeType = Literal[
    "rectangle", "circle", "ellipse", "polygon",
    "block", "cylinder", "sphere", "cone", "torus",
]

OperationType = Literal[
    "union", "difference", "intersection",
    "extrude", "revolve", "sweep", "work_plane",
]


class GeometryShape(BaseModel):
    """几何形状定义（2D / 3D）"""

    type: ShapeType = Field(..., description="几何形状类型")

    parameters: Dict[str, Any] = Field(
        ..., description="形状参数，如矩形的宽高、圆柱的半径与高度等"
    )

    position: Dict[str, float] = Field(
        default={"x": 0.0, "y": 0.0},
        description="形状位置坐标 (x, y[, z])"
    )

    rotation: Dict[str, float] = Field(
        default={},
        description="旋转角度（度），可选 rx/ry/rz"
    )

    name: str = Field(default="", description="形状名称（可选）")

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, v: Dict[str, Any], info) -> Dict[str, Any]:
        shape_type = info.data.get("type")

        if shape_type == "rectangle":
            if "width" not in v or "height" not in v:
                raise ValueError("矩形需要 width 和 height 参数")
            if v["width"] <= 0 or v["height"] <= 0:
                raise ValueError("矩形的宽高必须大于 0")

        elif shape_type == "circle":
            if "radius" not in v:
                raise ValueError("圆形需要 radius 参数")
            if v["radius"] <= 0:
                raise ValueError("圆的半径必须大于 0")

        elif shape_type == "ellipse":
            if "a" not in v or "b" not in v:
                raise ValueError("椭圆需要 a (长轴) 和 b (短轴) 参数")
            if v["a"] <= 0 or v["b"] <= 0:
                raise ValueError("椭圆的长轴和短轴必须大于 0")

        elif shape_type == "block":
            for key in ("width", "height", "depth"):
                if key not in v:
                    raise ValueError(f"长方体需要 {key} 参数")
                if v[key] <= 0:
                    raise ValueError(f"长方体的 {key} 必须大于 0")

        elif shape_type == "cylinder":
            if "radius" not in v or "height" not in v:
                raise ValueError("圆柱需要 radius 和 height 参数")
            if v["radius"] <= 0 or v["height"] <= 0:
                raise ValueError("圆柱的 radius 和 height 必须大于 0")

        elif shape_type == "sphere":
            if "radius" not in v:
                raise ValueError("球体需要 radius 参数")
            if v["radius"] <= 0:
                raise ValueError("球体的半径必须大于 0")

        elif shape_type == "cone":
            for key in ("radius_bottom", "height"):
                if key not in v:
                    raise ValueError(f"锥体需要 {key} 参数")
                if v[key] <= 0:
                    raise ValueError(f"锥体的 {key} 必须大于 0")
            if v.get("radius_top", 0) < 0:
                raise ValueError("锥体的 radius_top 不能小于 0")

        elif shape_type == "torus":
            if "radius_major" not in v or "radius_minor" not in v:
                raise ValueError("圆环需要 radius_major 和 radius_minor 参数")
            if v["radius_major"] <= 0 or v["radius_minor"] <= 0:
                raise ValueError("圆环的半径必须大于 0")
            if v["radius_minor"] >= v["radius_major"]:
                raise ValueError("圆环的 radius_minor 必须小于 radius_major")

        elif shape_type == "polygon":
            if "x" not in v or "y" not in v:
                raise ValueError("多边形需要 x 和 y 顶点坐标数组")
            if len(v["x"]) < 3 or len(v["y"]) < 3:
                raise ValueError("多边形至少需要 3 个顶点")
            if len(v["x"]) != len(v["y"]):
                raise ValueError("多边形的 x 和 y 数组长度必须一致")

        return v

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: Dict[str, float]) -> Dict[str, float]:
        if "x" not in v:
            v["x"] = 0.0
        if "y" not in v:
            v["y"] = 0.0
        return v

    def is_3d(self) -> bool:
        return self.type in SHAPE_3D


class GeometryOperation(BaseModel):
    """几何操作（布尔运算、拉伸、旋转等）"""

    type: OperationType = Field(..., description="操作类型")

    name: str = Field(..., description="操作名称/标签")

    input: List[str] = Field(
        default=[],
        description="输入形状/操作名称列表"
    )

    parameters: Dict[str, Any] = Field(
        default={},
        description="操作参数，如拉伸距离、旋转角度等"
    )

    keep_input: bool = Field(
        default=False,
        description="是否保留输入对象（布尔运算时）"
    )


class GeometryPlan(BaseModel):
    """几何建模计划"""

    shapes: List[GeometryShape] = Field(..., description="几何形状列表")

    operations: List[GeometryOperation] = Field(
        default=[],
        description="几何操作列表（布尔运算、拉伸、旋转等）"
    )

    dimension: Literal[2, 3] = Field(
        default=2,
        description="几何维度（2 = 2D，3 = 3D）"
    )

    units: str = Field(default="m", description="单位（默认：米）")

    model_name: str = Field(default="geometry_model", description="模型名称")

    @field_validator("shapes")
    @classmethod
    def validate_shapes(cls, v: List[GeometryShape]) -> List[GeometryShape]:
        if not v:
            raise ValueError("至少需要一个几何形状")
        return v

    @field_validator("dimension")
    @classmethod
    def validate_dimension_vs_shapes(cls, v: int, info) -> int:
        shapes = info.data.get("shapes", [])
        for shape in shapes:
            if isinstance(shape, GeometryShape) and shape.is_3d() and v == 2:
                raise ValueError(
                    f"形状 '{shape.type}' 为 3D 类型，但 dimension 设置为 2；"
                    "请将 dimension 设为 3"
                )
        return v

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "units": self.units,
            "dimension": self.dimension,
            "shapes": [shape.model_dump() for shape in self.shapes],
            "operations": [op.model_dump() for op in self.operations],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GeometryPlan":
        return cls(**data)
