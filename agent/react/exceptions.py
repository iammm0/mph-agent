from typing import Optional

from schemas.task import ReActTaskPlan


class PlanNeedsClarification(RuntimeError):
    """
    用于标识「Plan 阶段已完成，但存在澄清问题，需要前端先询问用户再继续执行」的早退异常。

    该异常会被 actions.do_run 捕获并转换为对前端的成功响应（ok=true, plan_needs_clarification=true），
    不视为真正的错误。
    """

    def __init__(self, message: str, plan: Optional[ReActTaskPlan] = None) -> None:
        super().__init__(message)
        self.plan = plan


class ReActNeedsReorchestrate(RuntimeError):
    """
    当迭代控制器判定为无效迭代或建议重新编排时，ReActAgent 抛出此异常。
    do_run 捕获后调用 PlannerOrchestrator.reorchestrate() 并返回给用户的可读说明。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message  # 含 [REORCHESTRATE] 前缀的完整消息

