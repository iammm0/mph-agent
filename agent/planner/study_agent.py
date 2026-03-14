"""研究类型 Planner Agent"""

import json
import re
from typing import Literal, Optional, cast

from agent.skills import get_skill_injector
from agent.utils.config import get_settings
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.utils.prompt_loader import prompt_loader
from schemas.study import StudyPlan, StudyType

logger = get_logger(__name__)

# 默认研究计划：稳态
DEFAULT_STUDY_PLAN = StudyPlan(studies=[StudyType(type="stationary", parameters={})])

ALLOWED_STUDY_TYPES = {"stationary", "time_dependent", "eigenvalue", "frequency"}


class StudyAgent:
    """研究类型 Planner Agent：解析自然语言为 StudyPlan。"""

    def __init__(self, api_key: Optional[str] = None, backend: Optional[str] = None, **kwargs):
        settings = get_settings()
        b = cast(
            Literal["deepseek", "kimi", "ollama", "openai-compatible"],
            backend or settings.llm_backend,
        )
        key = api_key or settings.get_api_key_for_backend(b)
        # 避免 kwargs 与显式参数重复导致 LLMClient(base_url=...) got multiple values
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
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"无法从响应中提取有效 JSON: {response_text[:200]}")

    def parse(self, user_input: str, context: Optional[str] = None) -> StudyPlan:
        """
        解析自然语言输入为研究计划。
        可选 context 为编排器注入的「其他 Agent 已完成的修改与错误」摘要。
        成功时返回 StudyPlan；LLM 不可用或解析失败时返回默认稳态研究。
        """
        user_input = (user_input or "").strip()
        if context:
            user_input = f"{context}\n\n当前步骤研究/求解需求：{user_input}"
        if not user_input:
            logger.info("研究输入为空，使用默认稳态")
            return DEFAULT_STUDY_PLAN

        if re.search(r"配置研究|研究配置|设置研究|求解|算一下", user_input) and not re.search(
            r"瞬态|时域|特征值|频域|time|eigen|frequen", user_input, re.I
        ):
            logger.info("检测到通用研究需求，使用默认稳态")
            return DEFAULT_STUDY_PLAN

        try:
            prompt = prompt_loader.format("planner", "study_planner", user_input=user_input)
            prompt = get_skill_injector().inject_into_prompt(user_input, prompt)
            response_text = self.llm.call(prompt, temperature=0.1, max_retries=2)
            json_data = self._extract_json_from_response(response_text)
            studies_data = json_data.get("studies", [])
            if not studies_data:
                return DEFAULT_STUDY_PLAN
            study_list = []
            for s in studies_data:
                t = s.get("type", "stationary")
                study_list.append(
                    StudyType(
                        type=t if t in ALLOWED_STUDY_TYPES else "stationary",
                        parameters=s.get("parameters", {}),
                    )
                )
            plan = StudyPlan(studies=study_list)
            logger.info("研究解析成功: %s 个研究", len(plan.studies))
            return plan
        except Exception as e:
            logger.warning("研究 LLM 解析失败，使用默认稳态: %s", e)
            return DEFAULT_STUDY_PLAN
