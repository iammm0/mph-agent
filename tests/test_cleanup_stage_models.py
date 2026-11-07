"""求解成功后只保留 *_latest.mph，清理过程模型。"""

from pathlib import Path

from agent.react.action_executor import ActionExecutor
from agent.schemas.task import ReActTaskPlan


def test_cleanup_stage_models_keeps_only_latest(tmp_path: Path):
    base = "model_abc"
    models = tmp_path
    for suffix in ("_geometry", "_material", "_physics", "_mesh", "_study", "_solve"):
        (models / f"{base}{suffix}.mph").write_text("stage", encoding="utf-8")
        (models / f"{base}{suffix}.mph.lock").write_text("lock", encoding="utf-8")
    latest = models / f"{base}_latest.mph"
    latest.write_text("latest-old", encoding="utf-8")
    solve = models / f"{base}_solve.mph"
    solve.write_text("solve-result", encoding="utf-8")

    plan = ReActTaskPlan(
        task_id="t1",
        user_input="t",
        model_name=base,
        model_path=str(solve),
        output_dir=str(models),
        execution_path=[],
    )
    ex = ActionExecutor()
    result = ex.cleanup_stage_models(plan)

    assert result["kept"] == str(latest.resolve())
    assert latest.exists()
    assert latest.read_text(encoding="utf-8") == "solve-result"
    assert plan.model_path == str(latest.resolve())
    for suffix in ("_geometry", "_material", "_physics", "_mesh", "_study", "_solve"):
        assert not (models / f"{base}{suffix}.mph").exists()
        assert not (models / f"{base}{suffix}.mph.lock").exists()
    assert latest.exists()
