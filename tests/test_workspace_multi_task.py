"""同一工作空间下多 Agent 任务隔离与旧布局迁移。"""

from pathlib import Path

from agent.utils.context_manager import (
    ContextManager,
    get_context_manager,
    sanitize_conversation_id,
)


def test_sanitize_conversation_id():
    assert sanitize_conversation_id("abc/../x") == "abc_.._x"
    assert sanitize_conversation_id("") == "default"


def test_two_tasks_isolated_dirs(tmp_path: Path):
    ws = tmp_path / "ws"
    a = get_context_manager(conversation_id="task-a", workspace_dir=str(ws))
    b = get_context_manager(conversation_id="task-b", workspace_dir=str(ws))
    assert a.context_dir != b.context_dir
    assert a.models_dir != b.models_dir
    assert "tasks" in str(a.context_dir).replace("\\", "/")
    assert a.context_dir.name == "task-a"
    assert b.context_dir.name == "task-b"
    (a.context_dir / "history.json").write_text("[]", encoding="utf-8")
    assert not (b.context_dir / "history.json").exists()


def test_delete_task_keeps_sibling(tmp_path: Path):
    ws = tmp_path / "ws"
    a = get_context_manager(conversation_id="a1", workspace_dir=str(ws))
    b = get_context_manager(conversation_id="b1", workspace_dir=str(ws))
    (a.models_dir / "m.mph").write_text("a", encoding="utf-8")
    (b.models_dir / "m.mph").write_text("b", encoding="utf-8")
    a.delete_conversation_and_models(wipe_workspace=False)
    assert not a.context_dir.exists()
    assert b.context_dir.exists()
    assert (b.models_dir / "m.mph").exists()


def test_migrate_legacy_shared_layout(tmp_path: Path):
    ws = tmp_path / "ws"
    (ws / "context").mkdir(parents=True)
    (ws / "models").mkdir(parents=True)
    (ws / "plans").mkdir(parents=True)
    (ws / "context" / "history.json").write_text("[]", encoding="utf-8")
    (ws / "models" / "old.mph").write_text("x", encoding="utf-8")
    (ws / "plans" / "plan.json").write_text("{}", encoding="utf-8")

    cm = ContextManager(workspace_root=ws, conversation_id="legacy1")
    assert (cm.context_dir / "history.json").exists()
    assert (cm.models_dir / "old.mph").exists()
    assert (cm.plans_dir / "plan.json").exists()
    assert not (ws / "context" / "history.json").exists()
