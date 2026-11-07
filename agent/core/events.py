"""EventBus：枚举事件类型、统一 Event 结构、按类型订阅、核心只 emit。"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Callable, Any, Optional


class EventType(str, Enum):
    """事件类型枚举，避免魔法字符串。"""
    PLAN_START = "plan_start"
    PLAN_END = "plan_end"
    THINK_CHUNK = "think_chunk"
    """LLM 流式输出的一小段文本（思维过程），data: { phase, chunk }"""
    LLM_STREAM_CHUNK = "llm_stream_chunk"
    # 可读的决策依据：为何走这一步、依据什么错误/规则调整
    DECISION = "decision"
    # 建模细致过程：规划完成后的步骤清单与每步输入要点
    MODELING_PROCESS = "modeling_process"
    ACTION_START = "action_start"
    ACTION_END = "action_end"
    EXEC_RESULT = "exec_result"
    OBSERVATION = "observation"
    CONTENT = "content"
    TASK_PHASE = "task_phase"
    ERROR = "error"
    DISCUSSION_CARD = "discussion_card"
    CASE_GENERATED = "case_generated"
    MATERIAL_START = "material_start"
    MATERIAL_END = "material_end"
    GEOMETRY_3D = "geometry_3d"
    COUPLING_ADDED = "coupling_added"
    # 具体步骤：开始/结束，便于交互板块逐步渲染
    STEP_START = "step_start"
    STEP_END = "step_end"
    # 一次构建任务结束（成功/失败/中止），携带最终模型路径，便于前端始终提供打开/预览
    RUN_END = "run_end"
    # 跑完后的下一步可执行建议（可直接作为用户提示词发送）
    NEXT_ACTIONS = "next_actions"
    # clawcode 集成事件：token 预算、计划 runtime 同步、worktree 进入/退出、ask-user 队列消费等
    TOKEN_BUDGET = "token_budget"
    # 单次 LLM 调用的实际 token 用量（优先 API usage；无则估算）
    TOKEN_USAGE = "token_usage"
    # 计算后端状态：CPU / GPU / GPU 待命
    COMPUTE_BACKEND = "compute_backend"
    # 求解实时进度（percent 0-100 + message）
    SOLVE_PROGRESS = "solve_progress"
    PLAN_RUNTIME_SYNC = "plan_runtime_sync"
    ASK_USER_RESOLVED = "ask_user_resolved"
    WORKTREE_ENTERED = "worktree_entered"
    WORKTREE_EXITED = "worktree_exited"
    # Capability scan：把 SkillInjector 对 3000+ COMSOL wrapper 的真实筛选过程暴露给前端
    CAPABILITY_SCAN_START = "capability_scan_start"
    """开始扫描可用能力。data: { phase, query, total, top_k, mode }"""
    CAPABILITY_SCAN_PROGRESS = "capability_scan_progress"
    """扫描进度（按批次推送）。data: { phase, scanned, total, current_names: string[<=5] }"""
    CAPABILITY_SCAN_HIT = "capability_scan_hit"
    """单条候选命中。data: { phase, name, title, score, matched_terms, category, invoke_mode }"""
    CAPABILITY_SCAN_END = "capability_scan_end"
    """扫描结束。data: { phase, total_scanned, hits: [...], elapsed_ms }"""


@dataclass
class Event:
    """统一事件体。"""
    type: EventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    iteration: Optional[int] = None


Handler = Callable[[Event], None]


class EventBus:
    """
    事件总线：subscribe(event_type, handler)、emit(event)。
    核心逻辑只调用 emit，UI 层订阅并更新界面。
    """

    def __init__(self):
        self._handlers: Dict[EventType, List[Handler]] = {}
        self._global_handlers: List[Handler] = []

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """按事件类型注册 handler。"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """注册接收所有事件的 handler（如日志、监控）。"""
        self._global_handlers.append(handler)

    def emit(self, event: Event) -> None:
        """发射事件，同步调用已注册的 handler。"""
        for h in self._global_handlers:
            try:
                h(event)
            except Exception:
                pass
        for h in self._handlers.get(event.type, []):
            try:
                h(event)
            except Exception:
                pass

    def emit_type(self, event_type: EventType, data: Optional[Dict[str, Any]] = None, iteration: Optional[int] = None) -> None:
        """便捷：构造 Event 并 emit。"""
        self.emit(Event(type=event_type, data=data or {}, iteration=iteration))
