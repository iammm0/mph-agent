"""Discussion stage handler for `/discuss`."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from agent.schemas.task import DiscussionCard

FINALIZE_KEYWORDS = (
    "结束探讨",
    "进入规划",
    "确认探讨结论",
    "探讨完成",
    "开始规划",
    "finish discuss",
    "done discuss",
)
REOPEN_KEYWORDS = ("继续探讨", "重新探讨", "reopen discuss")

# 短句寒暄/礼貌用语：不写入讨论卡，改由 LLM 自然回复（与「讨论卡已更新…」模板区分）
_CHITCHAT_LINE = re.compile(
    r"^(你好|您好|嗨|哈喽|在吗|在么|早上好|中午好|下午好|晚上好|谢谢|多谢|辛苦了|不客气|哈哈|哈哈哈|嗯|嗯嗯|好的|好滴|行|可以|OK|ok|Hi|Hello|hello|嗨喽|拜拜|再见|喂)[!！.。…~\s]*$",
    re.I,
)


def _split_points(text: str) -> List[str]:
    raw = re.split(r"[\n\r;；。.!?！？]+", text or "")
    out: List[str] = []
    for item in raw:
        s = item.strip().lstrip("-•*").strip()
        if s:
            out.append(s)
    return out


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        norm = item.strip()
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


def _looks_metric(text: str) -> bool:
    return bool(re.search(r"(误差|效率|温度|应力|压降|位移|功率|频率|响应|收敛|RMS|dB|%)", text))


def _looks_risk(text: str) -> bool:
    return bool(re.search(r"(风险|不稳定|不确定|可能失败|难以收敛|发散|敏感)", text))


def _looks_unknown(text: str) -> bool:
    return "?" in text or bool(re.search(r"(未知|不确定|待定|还没|尚未|需要确认|需要澄清)", text))


def _looks_principle(text: str) -> bool:
    return bool(re.search(r"(原理|机理|守恒|热传导|对流|辐射|应力|流体|电磁|耦合|方程)", text))


def _looks_solution(text: str) -> bool:
    return bool(re.search(r"(方案|可选|建议|可以|尝试|路线|建模思路|思路)", text))


def _looks_known_input(text: str) -> bool:
    return bool(re.search(r"\d", text)) or bool(
        re.search(r"(边界条件|材料|几何|尺寸|厚度|电流|电压|温度|流速|压力)", text)
    )


def is_chitchat_only(text: str) -> bool:
    """是否为短句闲聊（单行、无建模语义），用于跳过讨论卡增量。"""
    t = (text or "").strip()
    if not t or "\n" in t:
        return False
    if len(t) > 48:
        return False
    if re.search(
        r"(建模|COMSOL|mph|网格|物理场|边界|几何|求解|多物理|耦合|案例|模型)",
        t,
        re.I,
    ):
        return False
    if len(t) <= 24 and re.match(
        r"^(你好|您好|嗨|哈喽)[啊呀呢呗哦]*[!！.。…~\s]*$", t, re.I
    ):
        return True
    return bool(_CHITCHAT_LINE.match(t))


def format_card_brief(card: DiscussionCard) -> str:
    """供 LLM 参考的人类可读摘要（避免把字段名硬塞给用户）。"""
    lines: List[str] = []
    if card.physical_principles:
        lines.append("原理与机制：" + "；".join(card.physical_principles[:12]))
    if card.target_metrics:
        lines.append("目标与指标：" + "；".join(card.target_metrics[:12]))
    if card.known_inputs:
        lines.append("已知输入：" + "；".join(card.known_inputs[:12]))
    if card.unknowns:
        lines.append("待澄清：" + "；".join(card.unknowns[:12]))
    if card.candidate_solutions:
        lines.append("可行思路：" + "；".join(card.candidate_solutions[:12]))
    if card.risks:
        lines.append("风险：" + "；".join(card.risks[:8]))
    if card.assumptions:
        lines.append("假设与补充：" + "；".join(card.assumptions[:12]))
    if not lines:
        return "（尚未记录结构化要点，可引导用户补充物理场景、材料、边界与关心结果。）"
    return "\n".join(lines)


class DiscussionModeHandler:
    """Incrementally builds a structured discussion card."""

    def __init__(self, context_manager):
        self.context_manager = context_manager

    def _load_or_create_card(self) -> DiscussionCard:
        current = self.context_manager.load_discussion_card()
        if current:
            try:
                return DiscussionCard.model_validate(current)
            except Exception:
                pass
        return DiscussionCard()

    def _save_card(self, card: DiscussionCard) -> None:
        payload = card.model_dump(mode="json")
        self.context_manager.save_discussion_card(payload)

    def _invalidate_plan_if_needed(self) -> None:
        if hasattr(self.context_manager, "invalidate_confirmed_plan"):
            self.context_manager.invalidate_confirmed_plan()

    def _try_early_returns(
        self, text: str, lowered: str, card: DiscussionCard
    ) -> Optional[Tuple[str, DiscussionCard]]:
        if any(k in lowered for k in REOPEN_KEYWORDS):
            card.finalized = False
            card.updated_at = datetime.now()
            self._save_card(card)
            self._invalidate_plan_if_needed()
            return (
                "已重新打开探讨。可继续补充需求；改动讨论要点会作废已确认的建模计划。",
                card,
            )

        if any(k in lowered for k in FINALIZE_KEYWORDS):
            card.finalized = True
            card.updated_at = datetime.now()
            self._save_card(card)
            return (
                "探讨结论已标记完成。可随时切换到规划模式生成建模规划，"
                "也可继续补充；补充内容会自动重新打开探讨并作废已确认计划。",
                card,
            )
        return None

    def _update_card(self, card: DiscussionCard, user_input: str) -> bool:
        """Incrementally update card. Returns True if structured content changed."""
        before = (
            list(card.physical_principles),
            list(card.target_metrics),
            list(card.known_inputs),
            list(card.unknowns),
            list(card.assumptions),
            list(card.risks),
            list(card.candidate_solutions),
        )
        points = _split_points(user_input)
        for p in points:
            if _looks_risk(p):
                card.risks.append(p)
                continue
            if _looks_unknown(p):
                card.unknowns.append(p)
                continue
            if _looks_metric(p):
                card.target_metrics.append(p)
                continue
            if _looks_principle(p):
                card.physical_principles.append(p)
                continue
            if _looks_solution(p):
                card.candidate_solutions.append(p)
                continue
            if _looks_known_input(p):
                card.known_inputs.append(p)
                continue
            card.assumptions.append(p)

        card.physical_principles = _dedupe_keep_order(card.physical_principles)
        card.target_metrics = _dedupe_keep_order(card.target_metrics)
        card.known_inputs = _dedupe_keep_order(card.known_inputs)
        card.unknowns = _dedupe_keep_order(card.unknowns)
        card.assumptions = _dedupe_keep_order(card.assumptions)
        card.risks = _dedupe_keep_order(card.risks)
        card.candidate_solutions = _dedupe_keep_order(card.candidate_solutions)
        card.updated_at = datetime.now()
        after = (
            list(card.physical_principles),
            list(card.target_metrics),
            list(card.known_inputs),
            list(card.unknowns),
            list(card.assumptions),
            list(card.risks),
            list(card.candidate_solutions),
        )
        return before != after

    def process(self, user_input: str) -> Tuple[str, Dict[str, object]]:
        """兼容旧逻辑与单元测试：非 LLM 路径仍返回「讨论卡已更新」模板。"""
        text = (user_input or "").strip()
        card = self._load_or_create_card()
        lowered = text.lower()
        early = self._try_early_returns(text, lowered, card)
        if early:
            msg, c = early
            return msg, c.model_dump(mode="json")

        # New technical content always reopens discussion (soft finalize).
        card.finalized = False
        changed = self._update_card(card, text)
        self._save_card(card)
        if changed:
            self._invalidate_plan_if_needed()
        summary = (
            "讨论卡已更新："
            f"原理 {len(card.physical_principles)} 条，指标 {len(card.target_metrics)} 条，"
            f"已知输入 {len(card.known_inputs)} 条，未知项 {len(card.unknowns)} 条。"
            "可随时切换到规划或执行；需要标记探讨完成时可发送“结束探讨”。"
        )
        return summary, card.model_dump(mode="json")

    def try_resolve_control_messages(
        self, user_input: str
    ) -> Optional[Tuple[str, Dict[str, object]]]:
        """仅处理结束探讨 / 继续探讨等控制语；若命中则返回整轮回复。"""
        text = (user_input or "").strip()
        card = self._load_or_create_card()
        lowered = text.lower()
        early = self._try_early_returns(text, lowered, card)
        if early:
            msg, c = early
            return msg, c.model_dump(mode="json")
        return None
