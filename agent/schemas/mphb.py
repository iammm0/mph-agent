"""`.mphb` — mph-agent 专用「模型构建与操作过程」描述格式。

仅 mph-agent 识别并预览；普通编辑器打开只能看到 JSON，无过程时间线 UI。
扩展名：.mphb
MIME：application/vnd.mph-agent.build+json
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

MPHB_FORMAT = "mphb"
MPHB_KIND = "com.sensorai.mph-agent.build"
MPHB_VERSION = 1
MPHB_EXTENSION = ".mphb"
MPHB_MIME = "application/vnd.mph-agent.build+json"


class MphbStep(BaseModel):
    """单步建模/操作记录。"""

    index: int = Field(..., description="1-based step index")
    action: str = Field(..., description="如 create_geometry / solve")
    step_type: str = Field(default="", description="geometry/material/physics/...")
    label: str = Field(default="", description="展示名")
    # 规范状态；读写层会把 completed→success、error→failed 等别名归一化
    status: Literal[
        "pending", "running", "success", "warning", "skipped", "failed"
    ] = "pending"
    message: str = Field(default="")
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    model_path: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class MphbOperation(BaseModel):
    """operations.md 风格的细粒度操作行。"""

    time: str = ""
    step_type: str = ""
    message: str = ""
    result: str = ""
    model_path: Optional[str] = None


class MphbDocument(BaseModel):
    """完整 .mphb 文档。"""

    format: Literal["mphb"] = MPHB_FORMAT
    format_version: int = MPHB_VERSION
    kind: Literal["com.sensorai.mph-agent.build"] = MPHB_KIND
    generator: str = Field(default="mph-agent")
    created_at: str = Field(..., description="ISO-8601")
    title: str = Field(default="未命名构建过程")
    user_input: str = Field(default="")
    success: bool = True
    error: Optional[str] = None
    model_path: Optional[str] = Field(
        default=None, description="最终 .mph 路径（通常 *_latest.mph）"
    )
    workspace_dir: Optional[str] = None
    conversation_id: Optional[str] = None
    plan_description: Optional[str] = None
    steps: List[MphbStep] = Field(default_factory=list)
    operations: List[MphbOperation] = Field(default_factory=list)
    extras: Dict[str, Any] = Field(
        default_factory=dict,
        description="可选扩展：plan JSON、讨论卡引用等",
    )

    def is_valid_mphb(self) -> bool:
        return (
            self.format == MPHB_FORMAT
            and self.kind == MPHB_KIND
            and int(self.format_version) >= 1
        )
