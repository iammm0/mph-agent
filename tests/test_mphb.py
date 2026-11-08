"""`.mphb` 构建过程文件格式读写与组装测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.schemas.mphb import MPHB_KIND, MphbDocument, MphbStep
from agent.schemas.task import ExecutionStep, ReActTaskPlan
from agent.utils.mphb_io import (
    build_mphb_from_plan,
    dumps_mphb,
    is_mphb_path,
    load_mphb,
    loads_mphb,
    parse_operations_md,
    preview_dict,
    save_mphb,
)


def test_is_mphb_path():
    assert is_mphb_path("a/b/c.mphb")
    assert is_mphb_path(Path("x.MPHB"))
    assert not is_mphb_path("model.mph")


def test_roundtrip_save_load(tmp_path: Path):
    doc = MphbDocument(
        created_at="2026-01-01T00:00:00+00:00",
        title="测试构建",
        user_input="建一个立方体",
        success=True,
        model_path=str(tmp_path / "cube_latest.mph"),
        steps=[
            MphbStep(
                index=1,
                action="create_geometry",
                step_type="geometry",
                label="几何建模",
                status="success",
                message="ok",
            )
        ],
    )
    path = save_mphb(doc, tmp_path / "cube.mphb")
    assert path.suffix == ".mphb"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# MPHB")
    assert '"format": "mphb"' in text
    loaded = load_mphb(path)
    assert loaded.title == "测试构建"
    assert loaded.kind == MPHB_KIND
    assert loaded.steps[0].action == "create_geometry"
    preview = preview_dict(loaded)
    assert preview["step_count"] == 1
    assert preview["title"] == "测试构建"


def test_rejects_non_mphb_json():
    with pytest.raises(ValueError, match="不是有效的"):
        loads_mphb('{"format":"json","kind":"other"}')


def test_build_from_plan():
    plan = ReActTaskPlan(
        task_id="t_heat",
        model_name="heat",
        user_input="导热仿真",
        plan_description="二维导热",
        model_path="/tmp/heat_latest.mph",
        execution_path=[
            ExecutionStep(
                step_id="s1",
                action="create_geometry",
                step_type="geometry",
                status="completed",
                result={"message": "几何完成"},
            ),
            ExecutionStep(
                step_id="s2",
                action="solve",
                step_type="solve",
                status="completed",
                result={"message": "求解完成"},
            ),
        ],
    )
    doc = build_mphb_from_plan(plan, success=True, message="done", conversation_id="c1")
    assert doc.format == "mphb"
    assert len(doc.steps) == 2
    assert doc.steps[0].label == "几何建模"
    assert doc.success is True
    assert "导热" in doc.title or "二维" in doc.title


def test_parse_operations_md():
    text = """# 建模操作记录

- **geometry** (12:00:01): 创建矩形 - 成功
  模型: `C:/ws/models/a_geometry.mph`
- **solve** (12:05:09): 稳态求解 - 完成
"""
    ops = parse_operations_md(text)
    assert len(ops) == 2
    assert ops[0].step_type == "geometry"
    assert ops[0].model_path and "a_geometry.mph" in ops[0].model_path
    assert ops[1].step_type == "solve"


def test_dumps_has_kind():
    doc = MphbDocument(created_at="2026-01-01T00:00:00Z", title="t")
    s = dumps_mphb(doc)
    assert MPHB_KIND in s


def test_status_aliases_normalized_on_load():
    raw = {
        "format": "mphb",
        "format_version": 1,
        "kind": MPHB_KIND,
        "created_at": "2026-01-01T00:00:00Z",
        "title": "alias",
        "steps": [
            {"index": 1, "action": "create_geometry", "status": "completed"},
            {"index": 2, "action": "solve", "status": "error"},
            {"index": 3, "action": "add_material", "status": "ok"},
        ],
    }
    import json

    doc = loads_mphb(json.dumps(raw))
    assert doc.steps[0].status == "success"
    assert doc.steps[1].status == "failed"
    assert doc.steps[2].status == "success"


def test_stage_model_path_prefers_result_then_existing_file(tmp_path: Path):
    geom = tmp_path / "heat_geometry.mph"
    geom.write_text("x", encoding="utf-8")
    plan = ReActTaskPlan(
        task_id="t",
        model_name="heat",
        user_input="u",
        output_dir=str(tmp_path),
        model_path=str(tmp_path / "heat_latest.mph"),
        execution_path=[
            ExecutionStep(
                step_id="s1",
                action="create_geometry",
                step_type="geometry",
                status="completed",
                result={"message": "ok"},
            ),
            ExecutionStep(
                step_id="s2",
                action="solve",
                step_type="solve",
                status="completed",
                result={"model_path": str(tmp_path / "heat_solve.mph")},
            ),
        ],
    )
    doc = build_mphb_from_plan(plan, success=True)
    assert doc.steps[0].model_path and doc.steps[0].model_path.endswith("heat_geometry.mph")
    assert doc.steps[1].model_path and doc.steps[1].model_path.endswith("heat_solve.mph")
