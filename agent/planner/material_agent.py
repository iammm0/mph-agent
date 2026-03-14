"""材料建模 Planner Agent"""
import json
import re
from typing import Optional

from agent.utils.llm import LLMClient
from agent.utils.prompt_loader import prompt_loader
from agent.skills import get_skill_injector
from agent.utils.logger import get_logger
from agent.utils.config import get_settings
from schemas.material import MaterialPlan, MaterialDefinition, MaterialProperty, MaterialAssignment

logger = get_logger(__name__)

DEFAULT_MATERIAL_PLAN = MaterialPlan(
    materials=[
        MaterialDefinition(
            name="mat1",
            label="Steel",
            properties=[
                MaterialProperty(name="density", value=7850, unit="kg/m^3"),
                MaterialProperty(name="thermalconductivity", value=44.5, unit="W/(m*K)"),
                MaterialProperty(name="specificheat", value=475, unit="J/(kg*K)"),
                MaterialProperty(name="youngsmodulus", value=200e9, unit="Pa"),
                MaterialProperty(name="poissonsratio", value=0.3),
            ],
        )
    ],
    assignments=[MaterialAssignment(material_name="mat1", assign_all=True)],
)

BUILTIN_MATERIAL_KEYWORDS = {
    "铜": "Copper",
    "copper": "Copper",
    "钢": "Steel AISI 4340",
    "steel": "Steel AISI 4340",
    "铝": "Aluminum",
    "aluminum": "Aluminum",
    "aluminium": "Aluminum",
    "玻璃": "Glass (quartz)",
    "glass": "Glass (quartz)",
    "硅": "Silicon",
    "silicon": "Silicon",
    "空气": "Air",
    "air": "Air",
    "水": "Water",
    "water": "Water",
    "金": "Gold",
    "gold": "Gold",
    "银": "Silver",
    "silver": "Silver",
    "钛": "Titanium beta-21S",
    "titanium": "Titanium beta-21S",
}


class MaterialAgent:
    """材料建模 Planner Agent：解析自然语言为 MaterialPlan。"""

    def __init__(self, api_key: Optional[str] = None, backend: Optional[str] = None, **kwargs):
        settings = get_settings()
        b = backend or settings.llm_backend
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

    def parse(self, user_input: str, context: Optional[str] = None) -> MaterialPlan:
        """解析自然语言输入为材料计划。可选 context 为编排器注入的「其他 Agent 已完成的修改与错误」摘要。"""
        user_input = (user_input or "").strip()
        if context:
            user_input = f"{context}\n\n当前步骤材料需求：{user_input}"
        if not user_input:
            logger.info("材料输入为空，使用默认钢材")
            return DEFAULT_MATERIAL_PLAN

        # 快速关键词匹配：如果用户只简单提到一种材料
        for keyword, builtin_name in BUILTIN_MATERIAL_KEYWORDS.items():
            if keyword in user_input.lower():
                logger.info("关键词匹配到内置材料: %s -> %s", keyword, builtin_name)
                return MaterialPlan(
                    materials=[
                        MaterialDefinition(
                            name="mat1",
                            label=builtin_name,
                            builtin_name=builtin_name,
                        )
                    ],
                    assignments=[MaterialAssignment(material_name="mat1", assign_all=True)],
                )

        try:
            prompt = prompt_loader.format("planner", "material_planner", user_input=user_input)
            prompt = get_skill_injector().inject_into_prompt(user_input, prompt)
            response_text = self.llm.call(prompt, temperature=0.1, max_retries=2)
            json_data = self._extract_json_from_response(response_text)
            return MaterialPlan.from_dict(json_data)
        except Exception as e:
            logger.warning("材料 LLM 解析失败，使用默认钢材: %s", e)
            return DEFAULT_MATERIAL_PLAN
