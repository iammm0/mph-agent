"""mph-agent 保留的 clawcode 精简子集。

只服务三类旁路能力，不参与 COMSOL 执行：
- 会话记忆 compact / microcompact
- token 预算与计数
- PlanRuntime / TaskRuntime 计划镜像
"""

from .agent_session import AgentMessage, AgentSessionState
from .agent_types import BudgetConfig, UsageStats
from .compact import (
    AUTOCOMPACT_BUFFER_TOKENS,
    format_compact_summary,
    get_compact_user_summary_message,
)
from .microcompact import MicrocompactResult, microcompact_messages
from .plan_runtime import PlanRuntime, PlanStep
from .task_runtime import TaskRuntime
from .token_budget import (
    TokenBudgetSnapshot,
    calculate_token_budget,
    estimate_chat_overhead,
    format_token_budget,
)
from .tokenizer_runtime import (
    TokenCounterInfo,
    clear_token_counter_cache,
    count_tokens,
    describe_token_counter,
)

__all__ = [
    "AUTOCOMPACT_BUFFER_TOKENS",
    "AgentMessage",
    "AgentSessionState",
    "BudgetConfig",
    "MicrocompactResult",
    "PlanRuntime",
    "PlanStep",
    "TaskRuntime",
    "TokenBudgetSnapshot",
    "TokenCounterInfo",
    "UsageStats",
    "calculate_token_budget",
    "clear_token_counter_cache",
    "count_tokens",
    "describe_token_counter",
    "estimate_chat_overhead",
    "format_compact_summary",
    "format_token_budget",
    "get_compact_user_summary_message",
    "microcompact_messages",
]
