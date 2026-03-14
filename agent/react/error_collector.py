"""Error & Exception 收集器：收集各阶段/各层 Agent 的日志与报错，并做结构化分析供 IterationController 使用。"""

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.utils.logger import get_logger
from schemas.task import ErrorAnalysisResult, Observation

logger = get_logger(__name__)

# 错误归因规则：消息片段 -> (错误类型, 建议 Agent)
_ERROR_ATTRIBUTION_RULES = [
    # 材料属性缺失
    (r"未定义.*材料属性|材料属性.*未定义|固体\s*\d*.*所需的材料属性|所需.*材料属性\s*[kK]|缺.*k\s*", ("material_property_missing", "material")),
    (r"泊松比|杨氏模量|young|poisson|nu\s*[=:]|E\s*[=:]", ("material_property_missing", "material")),
    # 物理场/边界
    (r"物理场|边界条件|boundary|physics", ("physics_setup", "physics")),
    (r"求解器|稳态|瞬态|不收敛|solver|stationary|time.dependent", ("solver_or_study", "study")),
    (r"研究.*失败|study.*fail|配置研究", ("solver_or_study", "study")),
    # 几何
    (r"几何|无效.*几何|geometry|invalid.geom", ("geometry_error", "geometry")),
    # 网格
    (r"网格|mesh|划分", ("mesh_error", None)),  # 网格错误可能需回退到物理场或研究
]


@dataclass
class LogEntry:
    """单条收集记录"""

    step_id: str
    phase: str  # e.g. "act", "observe", "exception"
    payload: Dict[str, Any]
    message: Optional[str] = None  # 便于分析的短消息


class ErrorCollector:
    """
    收集核心执行层各阶段、各层 Agent 的日志与报错，并进行分析。
    不替代 Observer；Observer 负责单步结果 -> Observation，收集器负责聚合与分析。
    """

    def __init__(self, max_logs: int = 200):
        self._logs: deque = deque(maxlen=max_logs)

    def submit(self, step_id: str, phase: str, payload: Dict[str, Any]) -> None:
        """记录一条日志/错误。"""
        msg = None
        if isinstance(payload.get("message"), str):
            msg = payload["message"]
        elif isinstance(payload.get("result"), dict) and isinstance(payload["result"].get("message"), str):
            msg = payload["result"]["message"]
        elif isinstance(payload.get("observation"), dict) and isinstance(payload["observation"].get("message"), str):
            msg = payload["observation"]["message"]
        entry = LogEntry(step_id=step_id, phase=phase, payload=payload, message=msg)
        self._logs.append(entry)
        if phase == "exception" or (isinstance(payload.get("status"), str) and payload["status"] == "error"):
            logger.debug("ErrorCollector 记录: step_id=%s phase=%s msg=%s", step_id, phase, (msg or "")[:200])

    def get_recent_logs(self, n: int = 50) -> List[LogEntry]:
        """返回最近 n 条记录（从新到旧）。"""
        return list(self._logs)[-n:][::-1]

    def analyze(
        self,
        observations: Optional[List[Observation]] = None,
        recent_logs: Optional[List[LogEntry]] = None,
    ) -> Optional[ErrorAnalysisResult]:
        """
        对收集到的 error/exception 做结构化分析。
        使用规则匹配常见 COMSOL 错误；若无匹配则返回通用分析结果。
        """
        observations = observations or []
        recent_logs = recent_logs or self.get_recent_logs(30)
        # 汇总最近错误消息
        messages: List[str] = []
        for obs in observations:
            if obs.status in ("error", "warning") and obs.message:
                messages.append(obs.message)
        for entry in recent_logs:
            if entry.message and (entry.phase == "exception" or "error" in str(entry.payload.get("status", "")).lower()):
                messages.append(entry.message)
        combined = " ".join(messages) if messages else ""
        if not combined.strip():
            return ErrorAnalysisResult(
                error_type="unknown",
                raw_message=None,
                suggested_reason="无明确错误消息",
            )
        # 规则归因
        combined_lower = combined.lower()
        for pattern, (err_type, agent) in _ERROR_ATTRIBUTION_RULES:
            if re.search(pattern, combined, re.IGNORECASE):
                return ErrorAnalysisResult(
                    error_type=err_type,
                    suggested_agent=agent,
                    suggested_reason=f"规则匹配: {pattern[:40]}...",
                    raw_message=combined[:500],
                    suggest_reorchestrate=False,
                )
        # 默认：建议重新编排仅当消息很长或多次出现
        return ErrorAnalysisResult(
            error_type="unknown",
            raw_message=combined[:500],
            suggested_reason="未匹配到已知错误模式，建议检查日志或重新编排",
            suggest_reorchestrate=len(messages) >= 3,
        )
