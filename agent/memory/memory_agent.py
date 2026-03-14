"""
记忆 Agent：负责按会话整理用户建模指令的摘要式记忆。
采用 Python 原生异步 + 本地 SQLite/文件持久化，无 Redis、Celery 等外部依赖。
"""
from agent.memory.store import get_default_store
from agent.utils.logger import get_logger

logger = get_logger(__name__)


def update_conversation_memory(
    conversation_id: str,
    user_input: str,
    assistant_summary: str,
    success: bool = True,
) -> None:
    """
    更新会话的摘要记忆（同步入口）。
    当前实现：在本会话的 context 中已通过 add_conversation 写入历史，
    此处仅触发摘要重算。推荐在异步环境中使用 update_conversation_memory_async。
    """
    if not conversation_id:
        return
    try:
        store = get_default_store()
        store.update_summary_sync(conversation_id)
        logger.debug("会话 %s 摘要已更新", conversation_id[:8])
    except Exception as e:
        logger.warning("更新会话记忆失败: %s", e)


async def update_conversation_memory_async(
    conversation_id: str,
    user_input: str,
    assistant_summary: str,
    success: bool = True,
) -> None:
    """
    异步更新会话的摘要记忆。
    使用 asyncio + 本地文件/SQLite，不依赖 Redis、Celery，开箱即用。
    """
    store = get_default_store()
    await store.update_conversation_memory_async(
        conversation_id=conversation_id,
        user_input=user_input,
        assistant_summary=assistant_summary,
        success=success,
    )
