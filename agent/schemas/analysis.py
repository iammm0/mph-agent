"""错误分析与多角度修复假设的数据结构。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


FixAction = Literal[
    "update_material_property",
    "rollback_material",
    "rollback_physics",
    "rollback_mesh",
    "rollback_study",
    "inject_step",
    "modify_parameters",
    "reorchestrate",
]


class EvidenceHit(BaseModel):
    """一条来自某资料源的证据。"""

    source: Literal["skill", "doc_kb", "case_library", "rule", "plan_context", "api_capability"]
    title: str = ""
    snippet: str = ""
    url: str = ""
    score: float = 0.0


class FixHypothesis(BaseModel):
    """一个修复角度（可按置信度排序逐个尝试）。"""

    id: str = Field(..., description="假设唯一 id，用于去重与避免重复尝试")
    angle: str = Field(
        ...,
        description="视角标签，如 material_property / boundary / mesh / solver / geometry",
    )
    title: str = Field(..., description="短标题，给用户看")
    rationale: str = Field(default="", description="为何认为此角度能修好")
    sources: List[str] = Field(default_factory=list, description="依据的证据源")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    action: FixAction = Field(default="modify_parameters")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    tried: bool = False


class AnalysisReport(BaseModel):
    """多方查阅后的分析报告。"""

    error_summary: str = ""
    root_cause_hypothesis: str = ""
    evidence: List[EvidenceHit] = Field(default_factory=list)
    hypotheses: List[FixHypothesis] = Field(default_factory=list)
    selected_hypothesis_id: Optional[str] = None
    notes: str = ""

    def selected(self) -> Optional[FixHypothesis]:
        if not self.selected_hypothesis_id:
            return None
        for hyp in self.hypotheses:
            if hyp.id == self.selected_hypothesis_id:
                return hyp
        return None

    def next_untried(self) -> Optional[FixHypothesis]:
        for hyp in sorted(self.hypotheses, key=lambda h: -h.confidence):
            if not hyp.tried:
                return hyp
        return None
