"""网格划分 Planner Agent"""

import json
import re
from typing import Literal, Optional, cast

from agent.utils.config import get_settings
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.utils.prompt_loader import prompt_loader
from agent.skills import get_skill_injector
from schemas.mesh import MeshPlan, RefinementRegion

logger = get_logger(__name__)

# 默认网格计划：自由网格、正常质量
DEFAULT_MESH_PLAN = MeshPlan(
    element_size=None,
    sequence="free",
    quality="normal",
    refinement_regions=[],
    parameters={},
)

ALLOWED_QUALITY = {"coarse", "normal", "fine", "finer"}
ALLOWED_SEQUENCE = {"free", "sweep", "auto"}


class MeshAgent:
    """网格划分 Planner Agent：解析自然语言为 MeshPlan。"""

    def __init__(self, api_key: Optional[str] = None, backend: Optional[str] = None, **kwargs):
        settings = get_settings()
        b = cast(
            Literal["deepseek", "kimi", "ollama", "openai-compatible"],
            backend or settings.llm_backend,
        )
        key = api_key or settings.get_api_key_for_backend(b)
        base_url = kwargs.pop("base_url", None) or settings.get_base_url_for_backend(b)
        ollama_url = kwargs.pop("ollama_url", None) or settings.ollama_url
        model = kwargs.pop("model", None) or settings.get_model_for_backend(b)
        self.llm = LLMClient(
            backend=b,
            api_key=key,
            base_url=base_url,
            ollama_url=ollama_url,
            model=model,
        )

    def _extract_json_from_response(self, response_text: str) -> dict:
        """从 LLM 响应中提取 JSON。"""
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        m = re.search(r"\{.*\}", response_text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"无法从响应中提取有效 JSON: {response_text[:200]}")

    def parse(self, user_input: str, context: Optional[str] = None) -> MeshPlan:
        """
        解析自然语言输入为网格计划。
        可选 context 为编排器注入的「其他 Agent 已完成的修改与错误」摘要。
        """
        user_input = (user_input or "").strip()
        if context:
            user_input = f"{context}\n\n当前步骤网格划分需求：{user_input}"
        if not user_input:
            logger.info("网格输入为空，使用默认自由网格")
            return DEFAULT_MESH_PLAN

        try:
            prompt = prompt_loader.format("planner", "mesh_planner", user_input=user_input)
            prompt = get_skill_injector().inject_into_prompt(user_input, prompt)
            response_text = self.llm.call(prompt, temperature=0.1, max_retries=2)
            data = self._extract_json_from_response(response_text)
        except Exception as e:
            logger.warning("网格 LLM 解析失败，使用默认网格计划: %s", e)
            return DEFAULT_MESH_PLAN

        try:
            elem_size = data.get("element_size")
            if elem_size is not None and not isinstance(elem_size, (int, float)):
                elem_size = None
            seq = (data.get("sequence") or "free").strip().lower()
            if seq not in ALLOWED_SEQUENCE:
                seq = "free"
            quality = (data.get("quality") or "normal").strip().lower()
            if quality not in ALLOWED_QUALITY:
                quality = "normal"
            regions_data = data.get("refinement_regions") or []
            regions = []
            for r in regions_data:
                if not isinstance(r, dict):
                    continue
                regions.append(
                    RefinementRegion(
                        name=r.get("name", "refinement1"),
                        selection=r.get("selection", "all"),
                        element_size_ratio=r.get("element_size_ratio"),
                        max_element_size=r.get("max_element_size"),
                        parameters=r.get("parameters") or {},
                    )
                )
            plan = MeshPlan(
                element_size=elem_size,
                sequence=seq,
                quality=quality,
                refinement_regions=regions,
                parameters=data.get("parameters") or {},
            )
            logger.info("网格解析成功: sequence=%s, quality=%s", plan.sequence, plan.quality)
            return plan
        except Exception as e:
            logger.warning("网格计划构建失败，使用默认: %s", e)
            return DEFAULT_MESH_PLAN
