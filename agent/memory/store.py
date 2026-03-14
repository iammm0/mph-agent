"""
轻量化异步记忆存储：Python 原生 asyncio + 本地 SQLite/文件持久化。
无 Redis、Celery 等外部依赖，开箱即用。
"""
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.utils.config import get_install_dir
from agent.utils.logger import get_logger

logger = get_logger(__name__)

# 默认存储根目录
_DEFAULT_BASE = get_install_dir() / ".context"

# SQLite 表结构
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_summary (
    conversation_id TEXT PRIMARY KEY,
    summary_text TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    total_conversations INTEGER NOT NULL,
    recent_shapes TEXT,
    preferences TEXT
);
CREATE TABLE IF NOT EXISTS memory_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    user_input TEXT,
    plan_json TEXT,
    model_path TEXT,
    success INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_conversation ON memory_history(conversation_id);
"""


def _run_in_thread(fn, *args, **kwargs):
    """在线程池中执行同步函数，避免阻塞事件循环。"""
    return asyncio.to_thread(fn, *args, **kwargs)


class AsyncMemoryStore:
    """
    异步记忆存储：支持 SQLite 或文件两种后端。
    - backend="file"（默认）：沿用现有目录结构，通过 ContextManager 读写，开箱即用。
    - backend="sqlite": 单库多会话，表 memory_summary + memory_history；需配合将历史写入本 store 使用。
    """

    def __init__(
        self,
        base_path: Optional[Path] = None,
        backend: str = "file",
    ):
        self._base = Path(base_path) if base_path else _DEFAULT_BASE
        self._backend = backend
        self._db_path: Optional[Path] = None
        if backend == "sqlite":
            self._base.mkdir(parents=True, exist_ok=True)
            self._db_path = self._base / "memory.db"

    def _init_sqlite(self, conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA)

    def _get_connection(self) -> sqlite3.Connection:
        if not self._db_path:
            raise RuntimeError("SQLite 后端未配置 db_path")
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        self._init_sqlite(conn)
        return conn

    # ---------- 同步方法（供 to_thread 调用）----------

    def _sqlite_load_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cur = conn.execute(
                """SELECT timestamp, user_input, plan_json, model_path, success, error
                   FROM memory_history WHERE conversation_id = ? ORDER BY id""",
                (conversation_id,),
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                out.append({
                    "timestamp": r["timestamp"],
                    "user_input": r["user_input"] or "",
                    "plan": json.loads(r["plan_json"]) if r["plan_json"] else None,
                    "model_path": r["model_path"],
                    "success": bool(r["success"]),
                    "error": r["error"],
                })
            return out
        finally:
            conn.close()

    def _sqlite_save_history(self, conversation_id: str, history: List[Dict[str, Any]]) -> None:
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM memory_history WHERE conversation_id = ?", (conversation_id,))
            for h in history[-100:]:  # 只保留最近 100 条
                conn.execute(
                    """INSERT INTO memory_history
                       (conversation_id, timestamp, user_input, plan_json, model_path, success, error)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        conversation_id,
                        h.get("timestamp", ""),
                        h.get("user_input", ""),
                        json.dumps(h.get("plan"), ensure_ascii=False) if h.get("plan") else None,
                        h.get("model_path"),
                        1 if h.get("success", True) else 0,
                        h.get("error"),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _sqlite_load_summary(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cur = conn.execute(
                """SELECT summary_text, last_updated, total_conversations, recent_shapes, preferences
                   FROM memory_summary WHERE conversation_id = ?""",
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "summary": row["summary_text"],
                "last_updated": row["last_updated"],
                "total_conversations": row["total_conversations"],
                "recent_shapes": json.loads(row["recent_shapes"]) if row["recent_shapes"] else [],
                "preferences": json.loads(row["preferences"]) if row["preferences"] else {},
            }
        finally:
            conn.close()

    def _sqlite_save_summary(self, conversation_id: str, summary: Dict[str, Any]) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO memory_summary
                   (conversation_id, summary_text, last_updated, total_conversations, recent_shapes, preferences)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    summary.get("summary", ""),
                    summary.get("last_updated", ""),
                    int(summary.get("total_conversations", 0)),
                    json.dumps(summary.get("recent_shapes", []), ensure_ascii=False),
                    json.dumps(summary.get("preferences", {}), ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _file_update_summary_sync(self, conversation_id: str) -> None:
        """文件后端：通过 ContextManager 同步更新摘要（在线程中调用）。"""
        from agent.utils.context_manager import get_context_manager
        cm = get_context_manager(conversation_id)
        cm.update_summary()

    def _sqlite_update_summary_sync(self, conversation_id: str) -> None:
        """SQLite 后端：根据 history 计算摘要并写入 SQLite。"""
        from datetime import datetime
        history = self._sqlite_load_history(conversation_id)
        if not history:
            return
        recent_shapes: List[str] = []
        for entry in history[-20:]:
            plan = entry.get("plan") or {}
            for shape in plan.get("shapes", []):
                t = shape.get("type", "")
                if t and t not in recent_shapes:
                    recent_shapes.append(t)
        units_count: Dict[str, int] = {}
        for entry in history[-20:]:
            plan = entry.get("plan") or {}
            u = plan.get("units", "m")
            units_count[u] = units_count.get(u, 0) + 1
        preferred_unit = max(units_count.items(), key=lambda x: x[1])[0] if units_count else ""
        preferences = {"preferred_unit": preferred_unit} if preferred_unit else {}
        total = len(history)
        successful = sum(1 for e in history if e.get("success", True))
        recent_count = min(5, total)
        recent_entries = history[-recent_count:]
        parts = [f"总计 {total} 次对话，成功 {successful} 次。"]
        if recent_shapes:
            parts.append(f"最近使用的形状类型: {', '.join(recent_shapes)}。")
        if preferred_unit:
            parts.append(f"常用单位: {preferred_unit}。")
        parts.append("最近活动:")
        for entry in recent_entries:
            user_input = (entry.get("user_input") or "")[:50]
            status = "成功" if entry.get("success", True) else "失败"
            parts.append(f"  - {user_input}... ({status})")
        summary_text = "\n".join(parts)
        summary = {
            "summary": summary_text,
            "last_updated": datetime.now().isoformat(),
            "total_conversations": total,
            "recent_shapes": recent_shapes,
            "preferences": preferences,
        }
        self._sqlite_save_summary(conversation_id, summary)

    def update_summary_sync(self, conversation_id: str) -> None:
        """同步更新指定会话的摘要（供在 to_thread 中调用）。"""
        if not conversation_id:
            return
        if self._backend == "file":
            self._file_update_summary_sync(conversation_id)
        else:
            self._sqlite_update_summary_sync(conversation_id)
        logger.debug("会话 %s 摘要已更新", conversation_id[:8])

    # ---------- 异步 API ----------

    async def update_conversation_memory_async(
        self,
        conversation_id: str,
        user_input: str,
        assistant_summary: str,
        success: bool = True,
    ) -> None:
        """
        异步更新会话记忆（摘要）。
        不阻塞主线程，无外部服务依赖。
        """
        if not conversation_id:
            return
        try:
            await _run_in_thread(
                self.update_summary_sync,
                conversation_id,
            )
        except Exception as e:
            logger.warning("更新会话记忆失败: %s", e)

    def _file_load_summary_sync(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """文件后端：同步读取摘要并转为 dict。"""
        from dataclasses import asdict
        from agent.utils.context_manager import get_context_manager
        s = get_context_manager(conversation_id).load_summary()
        return asdict(s) if s else None

    async def get_summary_async(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """异步读取会话摘要。"""
        if self._backend != "sqlite":
            return await _run_in_thread(self._file_load_summary_sync, conversation_id)
        return await _run_in_thread(self._sqlite_load_summary, conversation_id)

    def _file_load_history_sync(self, conversation_id: str) -> List[Dict[str, Any]]:
        """文件后端：同步读取历史。"""
        from agent.utils.context_manager import get_context_manager
        return get_context_manager(conversation_id).load_history()

    async def get_history_async(self, conversation_id: str) -> List[Dict[str, Any]]:
        """异步读取会话历史。"""
        if self._backend != "sqlite":
            return await _run_in_thread(self._file_load_history_sync, conversation_id)
        return await _run_in_thread(self._sqlite_load_history, conversation_id)


def get_default_store(backend: str = "file") -> AsyncMemoryStore:
    """获取默认异步记忆存储（文件后端，与现有 ContextManager 一致）。"""
    return AsyncMemoryStore(backend=backend)
