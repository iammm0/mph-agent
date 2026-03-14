"""物理场建模 Planner Agent — 支持扩展物理场类型与边界/域/初始条件"""

import json
import re
from typing import Literal, Optional, cast

from agent.skills import get_skill_injector
from agent.utils.config import get_settings
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.utils.prompt_loader import prompt_loader
from schemas.physics import (
    BoundaryCondition,
    CouplingDefinition,
    DomainCondition,
    InitialCondition,
    PhysicsField,
    PhysicsPlan,
)

logger = get_logger(__name__)

DEFAULT_PHYSICS_PLAN = PhysicsPlan(fields=[PhysicsField(type="heat", parameters={})])

PHYSICS_TYPE_TO_COMSOL_TAG = {
    "heat": "HeatTransfer",
    "electromagnetic": "ElectromagneticWaves",
    "structural": "SolidMechanics",
    "fluid": "SinglePhaseFlow",
    "acoustics": "Acoustics",
    "piezoelectric": "Piezoelectric",
    "chemical": "ChemicalSpeciesTransport",
    "multibody": "MultibodyDynamics",
}

ALLOWED_TYPES = set(PHYSICS_TYPE_TO_COMSOL_TAG.keys())


class PhysicsAgent:
    """物理场建模 Planner Agent：解析自然语言为 PhysicsPlan。"""

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

    def _build_field(self, raw: dict) -> PhysicsField:
        """从 LLM 返回的 dict 构造 PhysicsField，含边界/域/初始条件。"""
        t = raw.get("type", "heat")
        if t not in ALLOWED_TYPES:
            t = "heat"

        bcs = [BoundaryCondition(**bc) for bc in raw.get("boundary_conditions", [])]
        dcs = [DomainCondition(**dc) for dc in raw.get("domain_conditions", [])]
        ics = [InitialCondition(**ic) for ic in raw.get("initial_conditions", [])]

        return PhysicsField(
            type=t,
            parameters=raw.get("parameters", {}),
            boundary_conditions=bcs,
            domain_conditions=dcs,
            initial_conditions=ics,
        )

    def parse(self, user_input: str, context: Optional[str] = None) -> PhysicsPlan:
        """解析自然语言为物理场计划。可选 context 为编排器注入的「其他 Agent 已完成的修改与错误」摘要。"""
        user_input = (user_input or "").strip()
        if context:
            user_input = f"{context}\n\n当前步骤物理场需求：{user_input}"
        if not user_input:
            logger.info("物理场输入为空，使用默认传热")
            return DEFAULT_PHYSICS_PLAN

        if re.search(r"加物理场|添加物理场|开始加物理场|设置物理场", user_input) and not re.search(
            r"电磁|流体|结构|力学|声学|压电|化学|多体", user_input
        ):
            logger.info("检测到通用物理场需求，使用默认传热")
            return DEFAULT_PHYSICS_PLAN

        try:
            prompt = prompt_loader.format("planner", "physics_planner", user_input=user_input)
            prompt = get_skill_injector().inject_into_prompt(user_input, prompt)
            response_text = self.llm.call(prompt, temperature=0.1, max_retries=2)
            json_data = self._extract_json_from_response(response_text)

            fields_raw = json_data.get("fields", [])
            if not fields_raw:
                return DEFAULT_PHYSICS_PLAN

            field_list = [self._build_field(f) for f in fields_raw]

            couplings = [CouplingDefinition(**c) for c in json_data.get("couplings", [])]

            plan = PhysicsPlan(fields=field_list, couplings=couplings)
            logger.info(
                "物理场解析成功: %s 个物理场, %s 个耦合", len(plan.fields), len(plan.couplings)
            )
            return plan
        except Exception as e:
            logger.warning("物理场 LLM 解析失败，使用默认传热: %s", e)
            return DEFAULT_PHYSICS_PLAN
