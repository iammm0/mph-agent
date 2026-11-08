"""`.mphb` 读写与从 ReAct 运行结果组装。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agent.schemas.mphb import (
    MPHB_EXTENSION,
    MPHB_KIND,
    MphbDocument,
    MphbOperation,
    MphbStep,
)
from agent.schemas.task import ReActTaskPlan
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_STEP_LABELS = {
    "create_geometry": "几何建模",
    "define_globals": "全局参数",
    "add_material": "材料设置",
    "update_material_property": "材料属性修补",
    "add_physics": "物理场与边界",
    "generate_mesh": "网格划分",
    "configure_study": "研究配置",
    "solve": "求解",
    "export_results": "结果导出",
    "evaluate_results": "结果求值",
    "set_parameters": "参数设置",
}

# action → 分阶段模型后缀（与 cleanup_stage_models / 落盘约定对齐）
_ACTION_STAGE_SUFFIX = {
    "create_geometry": "geometry",
    "define_globals": "geometry",
    "add_material": "material",
    "update_material_property": "material",
    "add_physics": "physics",
    "generate_mesh": "mesh",
    "configure_study": "study",
    "solve": "solve",
    "export_results": "latest",
    "evaluate_results": "latest",
    "set_parameters": "geometry",
}

_CANONICAL_STATUSES = frozenset(
    {"pending", "running", "success", "warning", "skipped", "failed"}
)


def is_mphb_path(path: Union[str, Path]) -> bool:
    return Path(path).suffix.lower() == MPHB_EXTENSION


def dumps_mphb(doc: MphbDocument, *, indent: int = 2) -> str:
    payload = doc.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def loads_mphb(text: str) -> MphbDocument:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空的 .mphb 内容")
    # 允许文件头注释行（# ...）
    if raw.startswith("#"):
        lines = raw.splitlines()
        body_lines = [ln for ln in lines if not ln.strip().startswith("#")]
        raw = "\n".join(body_lines).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(".mphb 根节点必须是 JSON 对象")
    fmt = str(data.get("format") or "")
    kind = str(data.get("kind") or "")
    if fmt != "mphb" or kind != MPHB_KIND:
        raise ValueError(
            f"不是有效的 mph-agent 构建过程文件（format={fmt!r}, kind={kind!r}）"
        )
    # 兼容旧文件里的 completed/error 等别名
    steps_raw = data.get("steps")
    if isinstance(steps_raw, list):
        for step in steps_raw:
            if isinstance(step, dict) and "status" in step:
                step["status"] = _status_of_step(step.get("status"))
    doc = MphbDocument.model_validate(data)
    if not doc.is_valid_mphb():
        raise ValueError("mphb 校验失败")
    return doc


def load_mphb(path: Union[str, Path]) -> MphbDocument:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    if p.suffix.lower() != MPHB_EXTENSION:
        raise ValueError(f"扩展名必须是 {MPHB_EXTENSION}，收到: {p.suffix}")
    return loads_mphb(p.read_text(encoding="utf-8"))


def save_mphb(doc: MphbDocument, path: Union[str, Path]) -> Path:
    p = Path(path).expanduser().resolve()
    if p.suffix.lower() != MPHB_EXTENSION:
        p = p.with_suffix(MPHB_EXTENSION)
    p.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# MPHB — mph-agent 模型构建与操作过程描述\n"
        "# 请使用 mph-agent 打开以预览时间线；用普通编辑器打开仅显示原始 JSON。\n"
    )
    p.write_text(header + dumps_mphb(doc), encoding="utf-8")
    return p


def _status_of_step(status: Optional[str]) -> str:
    """归一化为规范状态：pending/running/success/warning/skipped/failed。"""
    s = (status or "pending").strip().lower()
    aliases = {
        "ok": "success",
        "completed": "success",
        "complete": "success",
        "done": "success",
        "error": "failed",
        "fail": "failed",
        "cancelled": "skipped",
        "canceled": "skipped",
    }
    s = aliases.get(s, s)
    if s in _CANONICAL_STATUSES:
        return s
    return "pending"


def _model_stem_and_dir(plan: ReActTaskPlan) -> tuple[Optional[str], Optional[Path]]:
    model_name = getattr(plan, "model_name", None) or None
    out_dir = getattr(plan, "output_dir", None)
    model_path = getattr(plan, "model_path", None)
    directory: Optional[Path] = None
    stem: Optional[str] = None
    if out_dir:
        directory = Path(str(out_dir))
    if model_path:
        p = Path(str(model_path))
        directory = directory or p.parent
        stem = p.stem
        for suffix in (
            "_latest",
            "_solve",
            "_study",
            "_mesh",
            "_physics",
            "_material",
            "_geometry",
        ):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
    if not stem and model_name:
        stem = str(model_name)
    return stem, directory


def _stage_model_path_for_step(
    plan: ReActTaskPlan,
    *,
    action: str,
    result: Any,
) -> Optional[str]:
    """优先用步骤结果路径；否则按约定推断 base_<stage>.mph（存在才返回）。"""
    if isinstance(result, dict):
        for key in ("model_path", "saved_path", "path"):
            raw = result.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    stem, directory = _model_stem_and_dir(plan)
    if not stem or directory is None:
        return getattr(plan, "model_path", None)
    stage = _ACTION_STAGE_SUFFIX.get(str(action or ""))
    if not stage:
        return getattr(plan, "model_path", None)
    candidate = directory / f"{stem}_{stage}.mph"
    if candidate.exists():
        return str(candidate.resolve())
    # 求解后常见只剩 *_latest.mph
    if stage in ("solve", "latest"):
        latest = directory / f"{stem}_latest.mph"
        if latest.exists():
            return str(latest.resolve())
        final = getattr(plan, "model_path", None)
        if final:
            return str(final)
    return None


def build_mphb_from_plan(
    plan: ReActTaskPlan,
    *,
    success: bool,
    message: str = "",
    conversation_id: Optional[str] = None,
    workspace_dir: Optional[str] = None,
    operations: Optional[List[MphbOperation]] = None,
) -> MphbDocument:
    steps: List[MphbStep] = []
    for i, step in enumerate(plan.execution_path or [], start=1):
        result = step.result if isinstance(step.result, dict) else {}
        msg = ""
        if isinstance(result, dict):
            msg = str(result.get("message") or "")
        action = str(step.action or "")
        steps.append(
            MphbStep(
                index=i,
                action=action,
                step_type=str(step.step_type or ""),
                label=_STEP_LABELS.get(action, action),
                status=_status_of_step(getattr(step, "status", None)),  # type: ignore[arg-type]
                message=msg,
                model_path=_stage_model_path_for_step(plan, action=action, result=result),
                parameters=dict(step.parameters or {}),
            )
        )

    title = (plan.plan_description or plan.user_input or "构建过程")[:80].strip()
    err = None if success else (plan.error or message or "任务未成功")
    return MphbDocument(
        created_at=datetime.now(timezone.utc).isoformat(),
        title=title or "构建过程",
        user_input=plan.user_input or "",
        success=success,
        error=err,
        model_path=getattr(plan, "model_path", None),
        workspace_dir=workspace_dir or getattr(plan, "output_dir", None),
        conversation_id=conversation_id or getattr(plan, "task_id", None),
        plan_description=plan.plan_description,
        steps=steps,
        operations=list(operations or []),
        extras={
            "task_id": getattr(plan, "task_id", None),
            "model_name": getattr(plan, "model_name", None),
            "dimension": getattr(plan, "dimension", None),
            "end_message": message,
        },
    )


def parse_operations_md(text: str) -> List[MphbOperation]:
    """粗解析 operations.md 行，供写入 .mphb。"""
    out: List[MphbOperation] = []
    if not text:
        return out
    line_re = re.compile(
        r"^- \*\*(.+?)\*\* \((\d{1,2}:\d{2}:\d{2})\): (.+?)(?: - (.+))?$"
    )
    model_re = re.compile(r"模型:\s*`([^`]+)`")
    pending: Optional[MphbOperation] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = line_re.match(line)
        if m:
            if pending:
                out.append(pending)
            pending = MphbOperation(
                time=m.group(2),
                step_type=m.group(1),
                message=m.group(3).strip(),
                result=(m.group(4) or "").strip(),
            )
            continue
        if pending:
            mm = model_re.search(line)
            if mm:
                pending.model_path = mm.group(1).strip()
    if pending:
        out.append(pending)
    return out


def preview_dict(doc: MphbDocument) -> Dict[str, Any]:
    """前端预览用精简结构。"""
    return {
        "format": doc.format,
        "format_version": doc.format_version,
        "kind": doc.kind,
        "title": doc.title,
        "created_at": doc.created_at,
        "user_input": doc.user_input,
        "success": doc.success,
        "error": doc.error,
        "model_path": doc.model_path,
        "workspace_dir": doc.workspace_dir,
        "plan_description": doc.plan_description,
        "steps": [s.model_dump(mode="json") for s in doc.steps],
        "operations": [o.model_dump(mode="json") for o in doc.operations],
        "step_count": len(doc.steps),
        "operation_count": len(doc.operations),
    }


def default_mphb_path_for_model(model_path: Optional[str], plans_dir: Optional[Path] = None) -> Optional[Path]:
    if not model_path:
        return None
    p = Path(model_path)
    stem = p.stem
    for suffix in ("_latest", "_solve", "_study", "_mesh", "_physics", "_material", "_geometry"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if plans_dir is not None:
        return Path(plans_dir) / f"{stem}.mphb"
    return p.with_name(f"{stem}.mphb")
