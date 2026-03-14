"""网格划分数据结构定义"""
from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field


class RefinementRegion(BaseModel):
    """局部加密区域（可选）"""

    name: str = Field(default="refinement1", description="区域名称/标签")
    selection: str = Field(default="all", description="选择：域/边界 ID 或 'all'")
    element_size_ratio: Optional[float] = Field(
        default=None,
        description="相对全局单元尺寸的比例，如 0.5 表示更密",
    )
    max_element_size: Optional[float] = Field(default=None, description="最大单元尺寸（可选）")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="其他网格参数")


class MeshPlan(BaseModel):
    """网格划分计划"""

    # 全局或默认单元尺寸（米）；None 表示使用 COMSOL 默认
    element_size: Optional[float] = Field(default=None, description="全局单元尺寸（米）")
    # 序列类型：free（自由网格）、sweep（扫掠）等
    sequence: Literal["free", "sweep", "auto"] = Field(
        default="free",
        description="网格序列类型：free 自由划分、sweep 扫掠、auto 自动",
    )
    # 质量/精度档位：coarse / normal / fine / finer
    quality: Literal["coarse", "normal", "fine", "finer"] = Field(
        default="normal",
        description="网格质量档位",
    )
    refinement_regions: List[RefinementRegion] = Field(
        default_factory=list,
        description="需要加密的区域列表（可选）",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="其他网格参数，供执行层使用",
    )
