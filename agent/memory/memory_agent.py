"""
记忆 Agent：负责按会话整理用户建模指令的摘要式记忆。
每次 run 结束后由 Celery 后台任务（或同步）调用，判断本轮交互是否需要纳入摘要并更新会话记忆。
"""
from agent.utils.context_manager import get_context_manager
from agent.utils.logger import get_logger

logger = get_logger(__name__)


def update_conversation_memory(
    conversation_id: str,
    user_input: str,
    assistant_summary: str,
    success: bool = True,
) -> None:
    """
    更新会话的摘要记忆。
    当前实现：在本会话的 context 中已通过 add_conversation 写入历史，
    此处仅触发摘要重算（由 ContextManager 根据历史生成摘要）。
    后续可扩展为：先由 LLM 判断本轮是否需纳入摘要，再决定是否更新。
    """
    if not conversation_id:
        return
    try:
        cm = get_context_manager(conversation_id)
        # 历史已在 do_run 中 add_conversation，此处仅刷新摘要
        cm.update_summary()
        logger.debug("会话 %s 摘要已更新", conversation_id[:8])
    except Exception as e:
        logger.warning("更新会话记忆失败: %s", e)
