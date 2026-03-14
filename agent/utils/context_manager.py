"""上下文管理模块 - 按会话维度的对话历史和摘要"""
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict

from agent.utils.config import get_install_dir
from agent.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationEntry:
    """对话条目"""
    timestamp: str
    user_input: str
    plan: Optional[Dict[str, Any]] = None
    model_path: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


@dataclass
class ContextSummary:
    """上下文摘要"""
    summary: str
    last_updated: str
    total_conversations: int
    recent_shapes: List[str]  # 最近使用的形状类型
    preferences: Dict[str, Any]  # 用户偏好（如常用单位、尺寸范围等）


class ContextManager:
    """上下文管理器"""
    
    def __init__(self, context_dir: Optional[Path] = None, conversation_id: Optional[str] = None):
        """
        初始化上下文管理器

        Args:
            context_dir: 直接指定存储目录时使用
            conversation_id: 会话 ID，用于桌面多会话时按会话隔离存储（与 context_dir 二选一）
        """
        if context_dir is not None:
            self.context_dir = Path(context_dir)
        else:
            install_dir = get_install_dir()
            base = install_dir / ".context"
            if conversation_id:
                self.context_dir = base / conversation_id
            else:
                self.context_dir = base / "default"

        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.context_dir / "history.json"
        self.summary_file = self.context_dir / "summary.json"
        self.latest_model_file = self.context_dir / "latest_model.txt"
        self.operations_file = self.context_dir / "operations.md"

    def set_latest_model(self, model_path: str) -> None:
        """标记当前会话下最新修改的模型路径，便于用户查看。"""
        if not model_path:
            return
        try:
            self.latest_model_file.write_text(model_path.strip(), encoding="utf-8")
            logger.debug("已标记最新模型: %s", model_path)
        except Exception as e:
            logger.warning("写入最新模型标记失败: %s", e)

    def get_latest_model_path(self) -> Optional[str]:
        """读取当前会话下最新模型的路径。"""
        if not self.latest_model_file.exists():
            return None
        try:
            return self.latest_model_file.read_text(encoding="utf-8").strip() or None
        except Exception:
            return None

    def start_run_log(self, user_input: str) -> None:
        """开始一次建模运行的记录，写入 operations.md 的段落头。"""
        try:
            if not self.operations_file.exists():
                self.operations_file.write_text("# 建模操作记录\n\n", encoding="utf-8")
            head = f"\n---\n\n## {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 运行\n\n**用户输入**: {user_input}\n\n"
            with open(self.operations_file, "a", encoding="utf-8") as f:
                f.write(head)
        except Exception as e:
            logger.warning("写入 operations 运行头失败: %s", e)

    def append_operation(self, step_type: str, message: str, result_summary: str = "", model_path: Optional[str] = None) -> None:
        """将一次操作追加到 operations.md。"""
        try:
            line = f"- **{step_type}** ({datetime.now().strftime('%H:%M:%S')}): {message}"
            if result_summary:
                line += f" — {result_summary}"
            if model_path:
                line += f"\n  - 模型: `{model_path}`"
            line += "\n"
            with open(self.operations_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.warning("追加 operations 记录失败: %s", e)

    def add_conversation(
        self,
        user_input: str,
        plan: Optional[Dict[str, Any]] = None,
        model_path: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ) -> ConversationEntry:
        """
        添加对话记录
        
        Args:
            user_input: 用户输入
            plan: 解析后的计划
            model_path: 生成的模型路径
            success: 是否成功
            error: 错误信息
        
        Returns:
            ConversationEntry 对象
        """
        entry = ConversationEntry(
            timestamp=datetime.now().isoformat(),
            user_input=user_input,
            plan=plan,
            model_path=str(model_path) if model_path else None,
            success=success,
            error=error
        )
        
        # 加载历史记录
        history = self.load_history()
        history.append(asdict(entry))
        
        # 保存历史记录（只保留最近 100 条）
        if len(history) > 100:
            history = history[-100:]
        
        self.save_history(history)
        
        # 更新摘要
        self.update_summary()

        if model_path:
            self.set_latest_model(str(model_path))
        
        logger.debug(f"已添加对话记录: {user_input[:50]}...")
        return entry
    
    def load_history(self) -> List[Dict[str, Any]]:
        """加载对话历史"""
        if not self.history_file.exists():
            return []
        
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载历史记录失败: {e}")
            return []
    
    def save_history(self, history: List[Dict[str, Any]]):
        """保存对话历史"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史记录失败: {e}")
    
    def get_recent_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的对话历史"""
        history = self.load_history()
        return history[-limit:]
    
    def load_summary(self) -> Optional[ContextSummary]:
        """加载上下文摘要"""
        if not self.summary_file.exists():
            return None
        
        try:
            with open(self.summary_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return ContextSummary(**data)
        except Exception as e:
            logger.warning(f"加载摘要失败: {e}")
            return None
    
    def save_summary(self, summary: ContextSummary):
        """保存上下文摘要"""
        try:
            with open(self.summary_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(summary), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存摘要失败: {e}")
    
    def update_summary(self):
        """更新上下文摘要"""
        history = self.load_history()
        
        if not history:
            return
        
        # 提取最近使用的形状类型
        recent_shapes = []
        for entry in history[-20:]:  # 最近 20 条
            if entry.get('plan') and 'shapes' in entry['plan']:
                for shape in entry['plan']['shapes']:
                    shape_type = shape.get('type', '')
                    if shape_type and shape_type not in recent_shapes:
                        recent_shapes.append(shape_type)
        
        # 提取用户偏好
        preferences = {}
        units_count = {}
        for entry in history[-20:]:
            if entry.get('plan'):
                plan = entry['plan']
                # 统计常用单位
                unit = plan.get('units', 'm')
                units_count[unit] = units_count.get(unit, 0) + 1
        
        if units_count:
            preferences['preferred_unit'] = max(units_count.items(), key=lambda x: x[1])[0]
        
        # 生成摘要文本
        summary_text = self._generate_summary_text(history, recent_shapes, preferences)
        
        summary = ContextSummary(
            summary=summary_text,
            last_updated=datetime.now().isoformat(),
            total_conversations=len(history),
            recent_shapes=recent_shapes,
            preferences=preferences
        )
        
        self.save_summary(summary)
        logger.debug("上下文摘要已更新")

    def set_summary_text(self, text: str) -> None:
        """用户自定义：直接设置摘要文本（用于设置页编辑记忆）。"""
        current = self.load_summary()
        if current:
            summary = ContextSummary(
                summary=text.strip(),
                last_updated=datetime.now().isoformat(),
                total_conversations=current.total_conversations,
                recent_shapes=current.recent_shapes,
                preferences=current.preferences,
            )
        else:
            history = self.load_history()
            summary = ContextSummary(
                summary=text.strip(),
                last_updated=datetime.now().isoformat(),
                total_conversations=len(history),
                recent_shapes=[],
                preferences={},
            )
        self.save_summary(summary)
        logger.debug("用户已更新摘要文本")
    
    def _generate_summary_text(
        self,
        history: List[Dict[str, Any]],
        recent_shapes: List[str],
        preferences: Dict[str, Any]
    ) -> str:
        """生成摘要文本"""
        if not history:
            return "暂无对话历史"
        
        # 统计信息
        total = len(history)
        successful = sum(1 for e in history if e.get('success', True))
        
        # 最近活动
        recent_count = min(5, total)
        recent_entries = history[-recent_count:]
        
        summary_parts = [
            f"总计 {total} 次对话，成功 {successful} 次。",
        ]
        
        if recent_shapes:
            summary_parts.append(f"最近使用的形状类型: {', '.join(recent_shapes)}。")
        
        if preferences.get('preferred_unit'):
            summary_parts.append(f"常用单位: {preferences['preferred_unit']}。")
        
        if recent_entries:
            summary_parts.append("最近活动:")
            for entry in recent_entries:
                user_input = entry.get('user_input', '')[:50]
                status = "成功" if entry.get('success', True) else "失败"
                summary_parts.append(f"  - {user_input}... ({status})")
        
        return "\n".join(summary_parts)
    
    def get_context_for_planner(self) -> str:
        """获取用于 Planner 的上下文信息"""
        summary = self.load_summary()
        if not summary:
            return ""
        
        context_parts = []
        
        if summary.recent_shapes:
            context_parts.append(f"用户最近使用的形状类型: {', '.join(summary.recent_shapes)}")
        
        if summary.preferences.get('preferred_unit'):
            context_parts.append(f"用户常用单位: {summary.preferences['preferred_unit']}")
        
        # 添加最近几次对话的关键信息
        recent_history = self.get_recent_history(3)
        if recent_history:
            context_parts.append("最近的对话:")
            for entry in recent_history:
                if entry.get('success', True) and entry.get('plan'):
                    plan = entry['plan']
                    shapes_info = []
                    for shape in plan.get('shapes', []):
                        shape_type = shape.get('type', '')
                        if shape_type:
                            shapes_info.append(shape_type)
                    if shapes_info:
                        context_parts.append(f"  - 创建了: {', '.join(shapes_info)}")
        
        return "\n".join(context_parts) if context_parts else ""
    
    def clear_history(self):
        """清除对话历史"""
        if self.history_file.exists():
            self.history_file.unlink()
        if self.summary_file.exists():
            self.summary_file.unlink()
        logger.info("对话历史已清除")

    def delete_conversation_and_models(self) -> List[str]:
        """
        删除本会话对应的上下文与所有关联的 COMSOL 模型文件。
        返回已删除的模型文件路径列表（用于前端清理预览等）。
        """
        deleted_paths: List[str] = []
        history = self.load_history()
        for entry in history:
            path = entry.get("model_path")
            if not path:
                continue
            p = Path(path)
            if p.exists() and p.suffix.lower() == ".mph":
                try:
                    p.unlink()
                    deleted_paths.append(path)
                    logger.info("已删除对话关联模型: %s", path)
                except Exception as e:
                    logger.warning("删除模型文件失败 %s: %s", path, e)
        self.clear_history()
        if self.context_dir.exists():
            try:
                import shutil
                shutil.rmtree(self.context_dir, ignore_errors=True)
                logger.info("已删除会话上下文目录: %s", self.context_dir)
            except Exception as e:
                logger.warning("删除上下文目录失败: %s", e)
        return deleted_paths

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        history = self.load_history()
        summary = self.load_summary()
        
        return {
            "total_conversations": len(history),
            "successful": sum(1 for e in history if e.get('success', True)),
            "failed": sum(1 for e in history if not e.get('success', True)),
            "summary": summary.summary if summary else "暂无摘要",
            "recent_shapes": summary.recent_shapes if summary else [],
            "preferences": summary.preferences if summary else {},
        }

    def get_recent_models(self, limit: int = 20) -> List[Dict[str, Any]]:
        """当前会话最近生成的模型列表。"""
        history = self.load_history()
        out = []
        seen = set()
        latest_path = self.get_latest_model_path()
        for entry in reversed(history[-100:]):
            path = entry.get("model_path")
            if not path or path in seen or not Path(path).exists():
                continue
            seen.add(path)
            title = (entry.get("user_input") or Path(path).stem or path)[:50]
            out.append({
                "path": path,
                "title": title.strip() or Path(path).name,
                "timestamp": entry.get("timestamp", ""),
                "is_latest": path == latest_path,
            })
            if len(out) >= limit:
                break
        return out


def get_all_models_from_context(limit: int = 50) -> List[Dict[str, Any]]:
    """从所有会话历史汇总「我创建的 COMSOL 模型」列表；含 is_latest 标记。"""
    base = get_install_dir() / ".context"
    if not base.exists():
        return []
    collected: List[Dict[str, Any]] = []
    seen = set()
    for conv_dir in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime if p.is_dir() else 0, reverse=True):
        if not conv_dir.is_dir():
            continue
        hist_file = conv_dir / "history.json"
        latest_file = conv_dir / "latest_model.txt"
        latest_path = None
        if latest_file.exists():
            try:
                latest_path = latest_file.read_text(encoding="utf-8").strip() or None
            except Exception:
                pass
        if not hist_file.exists():
            continue
        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            continue
        for entry in reversed(history):
            path = entry.get("model_path")
            if not path or path in seen or not Path(path).exists():
                continue
            seen.add(path)
            title = (entry.get("user_input") or Path(path).stem or path)[:50]
            collected.append({
                "path": path,
                "title": title.strip() or Path(path).name,
                "timestamp": entry.get("timestamp", ""),
                "is_latest": path == latest_path,
            })
            if len(collected) >= limit:
                return collected
    return collected


# 默认（单会话）上下文管理器实例
_context_manager: Optional[ContextManager] = None


def get_context_manager(conversation_id: Optional[str] = None) -> ContextManager:
    """
    获取上下文管理器。
    若提供 conversation_id（桌面多会话），返回该会话专属的 manager；
    否则返回默认单例（CLI/单会话）。
    """
    global _context_manager
    if conversation_id:
        return ContextManager(conversation_id=conversation_id)
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager
