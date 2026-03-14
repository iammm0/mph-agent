"""
Planner 编排器：将用户提示词拆解为串行任务，并协调几何/材料/物理场/研究四个 Agent 执行。

参考 A2A 模式：通过 PlannerSharedContext 在各 Agent 之间传递「已完成的修改与错误」，
使每次遇到 error/exception 时，其余 Agent 能获知前面步骤的结果，便于重试或适配。
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent.planner.context import (
    PlannerSharedContext,
    SerialPlan,
    SerialPlanStep,
)
from agent.planner.geometry_agent import GeometryAgent
from agent.planner.material_agent import MaterialAgent
from agent.planner.physics_agent import PhysicsAgent
from agent.planner.mesh_agent import MeshAgent
from agent.planner.study_agent import StudyAgent
from agent.utils.config import get_settings
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.utils.prompt_loader import prompt_loader
from schemas.task import ClarifyingOption, ClarifyingQuestion, TaskPlan

logger = get_logger(__name__)

# 用于判断用户是否明确涉及材料/物理场/研究的简单关键词（后置过滤，避免仅几何需求被加料/加物理场）
_MATERIAL_KEYWORDS = ("材料", "赋", "钢材", "铜", "铝", "属性", "分配", "material")
_PHYSICS_KEYWORDS = (
    "物理场",
    "传热",
    "热传导",
    "静电场",
    "电场",
    "力学",
    "流体",
    "电磁",
    "physics",
    "heat",
    "solid",
)
# 网格：用户明确提到划分网格、网格精度、加密等时保留 mesh 步骤
_MESH_KEYWORDS = (
    "网格",
    "划分",
    "加密",
    "单元",
    "单元尺寸",
    "网格精度",
    "mesh",
    "element",
    "refine",
)
# 研究/求解：仅当用户明确要算、完整流程时才保留 study
_STUDY_KEYWORDS = (
    "研究",
    "求解",
    "仿真",
    "稳态",
    "瞬态",
    "计算",
    "算一下",
    "完整",
    "全流程",
    "study",
    "solve",
)
# 用户表达“只做到这里就行”的措辞，配合几何类描述时只保留几何（含「只建几何」「只创建几何」等）
_SCOPE_LIMIT_PHRASES = (
    "就行",
    "就可以",
    "就好",
    "只要",
    "仅",
    "只画",
    "只建",
    "建个",
    "画个",
    "就结束",
    "只建几何",
    "只创建几何",
    "仅几何",
)
_CASE_SEARCH_HINTS = (
    "没有灵感",
    "没灵感",
    "参考案例",
    "找案例",
    "案例库",
    "示例",
    "例子",
    "类似案例",
    "相关案例",
    "不知道从哪",
)
_CLARIFY_HINTS = ("想法", "方案", "思路", "初步", "大概", "可能", "考虑", "假设", "意向")
_FLUID_KEYWORDS = ("流体", "流动", "流速", "湍流", "层流", "气流", "液体", "空气", "水流")
_THERMAL_KEYWORDS = ("传热", "热", "温度", "散热", "热源", "热通量")
_STRUCTURAL_KEYWORDS = ("固体力学", "结构", "应力", "应变", "弹性", "载荷", "力学")
_EM_KEYWORDS = ("电磁", "电场", "静电", "磁场", "电流", "电压", "RF", "射频", "天线", "波导")


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _should_search_case_library(user_input: str) -> bool:
    text = (user_input or "").strip().lower()
    if not text:
        return False
    return any(k in text for k in _CASE_SEARCH_HINTS)


def _should_ask_clarifying_questions(user_input: str) -> bool:
    text = (user_input or "").strip()
    if not text:
        return False
    if any(k in text for k in _CLARIFY_HINTS):
        return True
    punct_count = len(re.findall(r"[。；;]", text))
    return len(text) >= 120 or punct_count >= 2


def _normalize_query(user_input: str) -> str:
    text = re.sub(r"\s+", " ", (user_input or "").strip())
    return text[:80]


def _parse_model_entries(html: str, base_url: str, limit: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    seen = set()
    if not html:
        return results
    for m in re.finditer(r'href="(/model/[^"]+)"', html, re.IGNORECASE):
        link = f"{base_url}{m.group(1)}"
        if link in seen:
            continue
        seen.add(link)
        snippet = html[m.start() : m.start() + 400]
        title_match = re.search(r'title="([^"]+)"', snippet, re.IGNORECASE)
        if not title_match:
            title_match = re.search(r'aria-label="([^"]+)"', snippet, re.IGNORECASE)
        if not title_match:
            title_match = re.search(r">([^<]{3,120})</a>", snippet, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""
        if not title:
            title = m.group(1).strip("/").split("/")[-1].replace("-", " ").title()
        results.append({"title": title, "url": link, "source": base_url})
        if len(results) >= limit:
            break
    return results


def _search_case_library(user_input: str, limit: int = 5) -> List[Dict[str, str]]:
    query = _normalize_query(user_input)
    if not query:
        return []
    headers = {"User-Agent": "Mozilla/5.0"}
    sites = [
        ("https://cn.comsol.com/models", "https://cn.comsol.com"),
        ("https://www.comsol.com/models", "https://www.comsol.com"),
    ]
    if not _contains_cjk(query):
        sites = [
            ("https://www.comsol.com/models", "https://www.comsol.com"),
            ("https://cn.comsol.com/models", "https://cn.comsol.com"),
        ]
    params_list = [{"search": query}, {"q": query}]
    for base, origin in sites:
        for params in params_list:
            try:
                response = requests.get(base, params=params, headers=headers, timeout=12)
                if response.status_code != 200:
                    continue
                entries = _parse_model_entries(response.text, origin, limit)
                if entries:
                    return entries
            except Exception:
                continue
    return []


def _is_em_thermal_scenario(user_input: str) -> bool:
    """判断是否为电磁（含线圈）+ 传热/对流场景，以便给出带具体默认值的澄清选项。"""
    text = (user_input or "").strip()
    has_em = any(k in text for k in _EM_KEYWORDS) or "线圈" in text
    has_thermal = any(k in text for k in _THERMAL_KEYWORDS) or "对流" in text
    return bool(has_em and has_thermal)


def _build_em_thermal_clarifying_questions() -> List[ClarifyingQuestion]:
    """
    电磁+传热场景的澄清问题：附上具体问题与示例数值选项，并设推荐默认。
    例如：线圈激励默认 100 A 电流，频率默认 50 kHz，对流默认 h=10、T_inf=293.15 K。
    """
    return [
        ClarifyingQuestion(
            id="q_coil_excitation",
            text="线圈的激励是电流还是电压？",
            type="single",
            options=[
                ClarifyingOption(
                    id="opt_current_100",
                    label="默认设置为 100 A 电流",
                    value="100A",
                    recommended=True,
                ),
                ClarifyingOption(
                    id="opt_voltage",
                    label="电压激励",
                    value="voltage",
                ),
                ClarifyingOption(id="opt_supplement", label="其他（请补充）", value="supplement"),
            ],
        ),
        ClarifyingQuestion(
            id="q_em_frequency",
            text="电磁场的工作频率是多少？",
            type="single",
            options=[
                ClarifyingOption(
                    id="opt_50khz",
                    label="默认设置为 50 kHz",
                    value="50kHz",
                    recommended=True,
                ),
                ClarifyingOption(id="opt_supplement", label="其他（请补充）", value="supplement"),
            ],
        ),
        ClarifyingQuestion(
            id="q_convection",
            text="对流换热系数和环境温度是否有具体要求？",
            type="single",
            options=[
                ClarifyingOption(
                    id="opt_h_Tinf",
                    label="默认设置为 h=10 W/(m²·K), T_inf=293.15 K",
                    value="h=10,T_inf=293.15",
                    recommended=True,
                ),
                ClarifyingOption(id="opt_supplement", label="其他（请补充）", value="supplement"),
            ],
        ),
    ]


def _build_clarifying_questions(user_input: str) -> List[str]:
    text = (user_input or "").strip()
    lower = text.lower()
    questions: List[str] = []
    has_number = bool(re.search(r"\d", text))
    if not has_number:
        questions.append("几何尺寸与单位是什么？是否有关键尺寸范围？")
    if not re.search(r"\b(2d|3d)\b", lower) and "二维" not in text and "三维" not in text:
        questions.append("模型是二维还是三维？是否需要轴对称简化？")
    if any(k in text for k in _STRUCTURAL_KEYWORDS):
        questions.append("结构材料是什么？若为线弹性，请提供 E 与 nu。")
        questions.append("载荷/约束的施加位置与类型是什么？")
    if any(k in text for k in _THERMAL_KEYWORDS):
        questions.append("热源/热通量/温度边界如何设定？是否有初始温度？")
    if any(k in text for k in _FLUID_KEYWORDS):
        questions.append("入口/出口边界条件是什么？流体性质与流动状态如何设定？")
    if any(k in text for k in _EM_KEYWORDS):
        questions.append("电磁激励与边界条件是什么？是否需要频率/电压/电流参数？")
    if "材料" in text and "自定义" in text:
        questions.append("材料属性是从数据库选取还是自定义输入？需要哪些参数？")
    if "网格" in text or "精度" in text:
        questions.append("网格精度目标是什么？是否有关键区域需要加密？")
    if any(k in text for k in _STUDY_KEYWORDS):
        questions.append("研究类型是稳态、瞬态还是频域？若为瞬态请给时间范围与步长。")
    if not questions:
        questions.append("是否有需要重点关注的输出指标或结果图？")
    return questions[:6]


def _wrap_clarifying_questions_as_structured(raw_questions: List[str]) -> List[ClarifyingQuestion]:
    """
    将简单的字符串问题包装为结构化 ClarifyingQuestion，供前端直接展示。
    第一个选项为推荐选项（采用当前描述中的合理默认），便于用户一键采纳。
    """
    structured: List[ClarifyingQuestion] = []
    for idx, q in enumerate(raw_questions, start=1):
        q_id = f"q{idx}"
        options = [
            ClarifyingOption(
                id="opt_recommended",
                label="推荐：采用当前描述中的合理默认",
                value="auto",
                recommended=True,
            ),
            ClarifyingOption(
                id="opt_skip", label="暂不限定，由我后续在 COMSOL 里补充", value="skip"
            ),
            ClarifyingOption(id="opt_supplement", label="其他（请补充）", value="supplement"),
        ]
        structured.append(
            ClarifyingQuestion(
                id=q_id,
                text=q.strip(),
                type="single",
                options=options,
            )
        )
    return structured


def _max_scope_from_keywords(
    has_material: bool, has_physics: bool, has_mesh: bool, has_study: bool
) -> str:
    """根据用户是否提到材料/物理场/网格/研究，返回允许的最大步骤类型。"""
    if has_study:
        return "study"
    if has_mesh:
        return "mesh"
    if has_physics:
        return "physics"
    if has_material:
        return "material"
    return "geometry"


def _filter_steps_by_user_intent(
    user_input: str, steps: List[SerialPlanStep]
) -> List[SerialPlanStep]:
    """
    根据用户输入过滤步骤：
    - 未明确涉及材料/物理场/网格/研究时只保留 geometry；
    - 若用户措辞明显限定为「仅几何」，则只保留 geometry；
    - 否则按用户提到的最大范围截断：geometry → material → physics → mesh → study。
    """
    if not steps:
        return steps
    raw = (user_input or "").strip()
    text = raw.lower()
    has_material = any(k in text for k in _MATERIAL_KEYWORDS)
    has_physics = any(k in text for k in _PHYSICS_KEYWORDS)
    has_mesh = any(k in text for k in _MESH_KEYWORDS)
    has_study = any(k in text for k in _STUDY_KEYWORDS)

    # 用户说了“只/仅…就行”且未明确要材料/物理场/网格/求解 → 视为仅几何
    has_scope_limit = any(p in text for p in _SCOPE_LIMIT_PHRASES)
    if has_scope_limit and not (has_material or has_physics or has_mesh or has_study):
        geometry_only = [s for s in steps if (s.agent_type or "").strip().lower() == "geometry"]
        if geometry_only:
            return geometry_only
        return [
            SerialPlanStep(
                step_index=1, agent_type="geometry", description="几何建模", input_snippet=raw
            ),
        ]

    # 按允许的最大范围截断步骤（geometry → material → physics → mesh → study）
    order = ("geometry", "material", "physics", "mesh", "study")
    max_scope = _max_scope_from_keywords(has_material, has_physics, has_mesh, has_study)
    try:
        max_index = order.index(max_scope)
    except ValueError:
        max_index = 0
    allowed = set(order[: max_index + 1])
    filtered = [s for s in steps if (s.agent_type or "").strip().lower() in allowed]
    if not filtered:
        filtered = [
            SerialPlanStep(
                step_index=1, agent_type="geometry", description="几何建模", input_snippet=raw
            ),
        ]
    else:
        # 重新连续编号
        filtered = [
            SerialPlanStep(
                step_index=i,
                agent_type=s.agent_type,
                description=s.description,
                input_snippet=s.input_snippet,
            )
            for i, s in enumerate(filtered, start=1)
        ]
    return filtered


def _extract_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON。支持裸 JSON、```json 块、首段 { } 块；对常见 LLM 错误（尾部逗号等）做一次修复再解析。"""
    raw = (text or "").strip()
    if not raw:
        return {}
    # 尝试直接解析
    for candidate in [raw, None]:
        if candidate is None:
            m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
            candidate = m.group(1) if m else None
        if candidate is None:
            m = re.search(r"\{[\s\S]*\}", raw)
            candidate = m.group(0) if m else None
        if not candidate:
            continue
        # 常见 LLM 错误：尾部逗号、单引号
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        for s in (fixed, candidate):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"无法从响应中提取 JSON: {raw[:300]}")


class PlannerOrchestrator:
    """
    Planner 层总编排 Agent。

    - 使用 LLM 将用户提示词拆解为串行任务（geometry → material → physics → mesh → study）。
    - 按顺序调用五个子 Agent，并维护共享上下文；每个 Agent 执行后更新上下文，
      使后续步骤或错误处理时能获知「其余 Agent 做了哪些修改」。
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        settings = get_settings()
        self.llm = LLMClient(
            backend=backend or settings.llm_backend,
            api_key=api_key or settings.get_api_key_for_backend(backend or settings.llm_backend),
            base_url=base_url or settings.get_base_url_for_backend(backend or settings.llm_backend),
            ollama_url=ollama_url or settings.ollama_url,
            model=model or settings.get_model_for_backend(backend or settings.llm_backend),
        )
        self._geometry_agent = GeometryAgent(
            backend=backend, api_key=api_key, base_url=base_url, ollama_url=ollama_url, model=model
        )
        self._material_agent = MaterialAgent(
            backend=backend, api_key=api_key, base_url=base_url, ollama_url=ollama_url, model=model
        )
        self._physics_agent = PhysicsAgent(
            backend=backend, api_key=api_key, base_url=base_url, ollama_url=ollama_url, model=model
        )
        self._mesh_agent = MeshAgent(
            backend=backend, api_key=api_key, base_url=base_url, ollama_url=ollama_url, model=model
        )
        self._study_agent = StudyAgent(
            backend=backend, api_key=api_key, base_url=base_url, ollama_url=ollama_url, model=model
        )

    def _default_serial_plan(self, user_input: str) -> SerialPlan:
        """JSON 解析或步骤构造失败时的兜底计划：单步几何。"""
        return SerialPlan(
            steps=[
                SerialPlanStep(
                    step_index=1,
                    agent_type="geometry",
                    description="几何建模",
                    input_snippet=(user_input or "").strip() or "几何建模",
                )
            ],
            plan_description=None,
        )

    def decompose(self, user_input: str) -> SerialPlan:
        """
        将用户提示词拆解为串行任务步骤。

        Returns:
            SerialPlan: 有序步骤列表（geometry → material → physics → study）。
        """
        logger.info("编排器分解用户需求: %s", user_input[:80])
        try:
            prompt = prompt_loader.format(
                "planner", "orchestrator_decompose", user_input=user_input
            )
        except FileNotFoundError:
            prompt = (
                "将以下 COMSOL 建模需求拆解为串行步骤，步骤类型为 geometry、material、physics、mesh、study。"
                '仅输出 JSON：{"steps": [{"step_index": 1, "agent_type": "geometry", "description": "...", "input_snippet": "..."}, ...], "plan_description": "..."}\n\n'
                f"用户需求：{user_input}"
            )

        try:
            response = self.llm.call(prompt, temperature=0.1, max_retries=2)
            data = _extract_json(response)
        except Exception as e:
            logger.warning("编排器 LLM 调用或 JSON 解析失败，使用兜底单步几何计划: %s", e)
            return self._default_serial_plan(user_input)

        try:
            raw_steps = data.get("steps")
            if not isinstance(raw_steps, list):
                raw_steps = []
            steps = []
            for s in raw_steps:
                if not isinstance(s, dict):
                    continue
                at = (s.get("agent_type") or "").strip().lower()
                if at not in ("geometry", "material", "physics", "mesh", "study"):
                    continue
                steps.append(
                    SerialPlanStep(
                        step_index=len(steps) + 1,
                        agent_type=at,
                        description=s.get("description", ""),
                        input_snippet=s.get("input_snippet", ""),
                    )
                )
            if not steps:
                steps = [
                    SerialPlanStep(
                        step_index=1,
                        agent_type="geometry",
                        description="几何建模",
                        input_snippet=user_input,
                    ),
                ]
            # 后置过滤：若用户输入未明确涉及材料/物理场/研究，则只保留几何步骤
            steps = _filter_steps_by_user_intent(user_input, steps)

            plan = SerialPlan(steps=steps, plan_description=data.get("plan_description"))

            # 优先使用 LLM 直接产出的结构化 clarifying_questions
            cq_data = data.get("clarifying_questions") or None
            if isinstance(cq_data, list) and cq_data:
                items: List[ClarifyingQuestion] = []
                for i, item in enumerate(cq_data, start=1):
                    try:
                        if "id" not in item or not str(item.get("id", "")).strip():
                            item = {**item, "id": f"q{i}"}
                        if not item.get("options"):
                            item["options"] = [
                                {"id": "opt_recommended", "label": "推荐：采用当前描述中的合理默认", "value": "auto", "recommended": True},
                                {"id": "opt_skip", "label": "暂不限定，由我后续在 COMSOL 里补充", "value": "skip"},
                                {"id": "opt_supplement", "label": "其他（请补充）", "value": "supplement"},
                            ]
                        items.append(ClarifyingQuestion.model_validate(item))
                    except Exception:
                        continue
                if items:
                    plan.clarifying_questions = items

            logger.info("编排器分解得到 %s 个步骤", len(plan.steps))
            return plan
        except Exception as e:
            logger.warning("编排器步骤构造或计划构建失败，使用兜底单步几何计划: %s", e)
            return self._default_serial_plan(user_input)

    def run(
        self,
        user_input: str,
        context: Optional[str] = None,
        shared_context: Optional[PlannerSharedContext] = None,
    ) -> Tuple[TaskPlan, PlannerSharedContext, SerialPlan]:
        """
        执行串行计划：按步骤调用对应 Agent，更新共享上下文，返回完整任务计划与上下文。

        Args:
            user_input: 用户原始输入。
            context: 可选的外部上下文（如会话摘要）。
            shared_context: 可选的外部共享上下文；若不传则新建一个。

        Returns:
            (TaskPlan, PlannerSharedContext, SerialPlan): 任务计划、共享上下文、串行计划（含 plan_description）。
        """
        serial_plan = self.decompose(user_input)
        if _should_ask_clarifying_questions(user_input) and not serial_plan.clarifying_questions:
            if _is_em_thermal_scenario(user_input):
                serial_plan.clarifying_questions = _build_em_thermal_clarifying_questions()
            else:
                raw_q = _build_clarifying_questions(user_input)
                serial_plan.clarifying_questions = _wrap_clarifying_questions_as_structured(raw_q)
        if _should_search_case_library(user_input):
            serial_plan.case_library_suggestions = _search_case_library(user_input)
        ctx = shared_context or PlannerSharedContext(user_input=user_input)
        ctx.user_input = user_input

        task_plan = TaskPlan()
        agents = {
            "geometry": ("geometry", self._geometry_agent, "geometry_plan"),
            "material": ("material", self._material_agent, "material"),
            "physics": ("physics", self._physics_agent, "physics"),
            "mesh": ("mesh", self._mesh_agent, "mesh"),
            "study": ("study", self._study_agent, "study"),
        }

        for step in serial_plan.steps:
            agent_type = step.agent_type
            if agent_type not in agents:
                logger.warning("未知 agent_type: %s，跳过", agent_type)
                continue
            _, agent, attr = agents[agent_type]
            step_input = (step.input_snippet or step.description or user_input).strip()
            # 注入「其他 Agent 已完成的修改与错误」到该步的上下文
            other_ctx = ctx.get_context_for_agent(for_agent_type=agent_type)
            combined_context = (
                (context or "") + "\n\n【其他 Agent 已完成的修改与错误】\n" + other_ctx
            )

            try:
                if agent_type == "geometry":
                    sub_plan = agent.parse(step_input, context=combined_context)
                    task_plan.geometry = sub_plan
                    summary = f"{len(sub_plan.shapes)} 个形状, {len(sub_plan.operations)} 个操作, {sub_plan.dimension}D"
                    ctx.append_success(step.step_index, agent_type, summary, raw_result=sub_plan)
                elif agent_type == "material":
                    sub_plan = agent.parse(step_input, context=combined_context)
                    task_plan.material = sub_plan
                    summary = f"{len(sub_plan.materials)} 种材料"
                    ctx.append_success(step.step_index, agent_type, summary, raw_result=sub_plan)
                elif agent_type == "physics":
                    sub_plan = agent.parse(step_input, context=combined_context)
                    task_plan.physics = sub_plan
                    summary = f"{len(sub_plan.fields)} 个物理场"
                    ctx.append_success(step.step_index, agent_type, summary, raw_result=sub_plan)
                elif agent_type == "mesh":
                    sub_plan = agent.parse(step_input, context=combined_context)
                    task_plan.mesh = sub_plan
                    summary = f"sequence={sub_plan.sequence}, quality={sub_plan.quality}"
                    ctx.append_success(step.step_index, agent_type, summary, raw_result=sub_plan)
                elif agent_type == "study":
                    sub_plan = agent.parse(step_input, context=combined_context)
                    task_plan.study = sub_plan
                    summary = f"{len(sub_plan.studies)} 个研究"
                    ctx.append_success(step.step_index, agent_type, summary, raw_result=sub_plan)
            except Exception as e:
                err_msg = str(e)
                logger.exception("Planner 步骤 %s (%s) 执行失败", step.step_index, agent_type)
                ctx.append_failure(step.step_index, agent_type, err_msg)
                # 继续执行后续步骤，后续 Agent 可通过 ctx 看到本步失败信息
                if agent_type == "geometry" and not task_plan.geometry:
                    from schemas.geometry import GeometryPlan

                    task_plan.geometry = GeometryPlan(
                        model_name="model", units="m", dimension=2, shapes=[], operations=[]
                    )
                elif agent_type == "material" and not task_plan.material:
                    from agent.planner.material_agent import DEFAULT_MATERIAL_PLAN

                    task_plan.material = DEFAULT_MATERIAL_PLAN
                elif agent_type == "physics" and not task_plan.physics:
                    from agent.planner.physics_agent import DEFAULT_PHYSICS_PLAN

                    task_plan.physics = DEFAULT_PHYSICS_PLAN
                elif agent_type == "mesh" and not task_plan.mesh:
                    from agent.planner.mesh_agent import DEFAULT_MESH_PLAN

                    task_plan.mesh = DEFAULT_MESH_PLAN
                elif agent_type == "study" and not task_plan.study:
                    from agent.planner.study_agent import DEFAULT_STUDY_PLAN

                    task_plan.study = DEFAULT_STUDY_PLAN

        return task_plan, ctx, serial_plan

    def reorchestrate(
        self,
        user_input: str,
        failure_summary: str,
        current_plan_snapshot: Optional[Dict[str, Any]] = None,
        context: Optional[str] = None,
    ) -> Tuple[TaskPlan, PlannerSharedContext, SerialPlan, str]:
        """
        带失败上下文的重新编排。当迭代控制器判定为无效迭代或收集器建议重新编排时，
        由调用方传入用户原始需求与失败原因，编排器据此重新分解任务并返回新计划及给用户的可读说明。

        Args:
            user_input: 用户原始建模需求。
            failure_summary: 上次执行失败原因摘要（如「同一错误已重复出现」「未定义材料属性 k」等）。
            current_plan_snapshot: 当前计划快照（可选），用于在 prompt 中提示 LLM 参考。
            context: 可选外部上下文（如会话摘要）。

        Returns:
            (TaskPlan, PlannerSharedContext, SerialPlan, user_message): 新任务计划、共享上下文、
            串行计划、以及给用户的可读说明（如「因…问题，已重新编排任务，请确认后再次执行」）。
        """
        combined_input = (
            (user_input or "").strip()
            + "\n\n【上次执行失败原因，请据此调整计划或补充缺失设置】\n"
            + (failure_summary or "").strip()
        )
        if current_plan_snapshot:
            try:
                combined_input += "\n\n【当前计划摘要（供参考）】\n" + json.dumps(
                    current_plan_snapshot, ensure_ascii=False, indent=2
                )[:800]
            except Exception:
                pass
        task_plan, ctx, serial_plan = self.run(combined_input, context=context, shared_context=None)
        user_message = (
            "因执行过程中遇到问题（" + (failure_summary or "").strip()[:100] + "），"
            "已根据失败原因重新编排任务。请确认新计划后再次执行建模流程。"
        )
        logger.info("重新编排完成，步骤数: %s", len(serial_plan.steps))
        return task_plan, ctx, serial_plan, user_message
