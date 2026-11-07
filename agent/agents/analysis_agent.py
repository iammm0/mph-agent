"""错误分析 Agent：多方查阅资料，提出多角度修复假设并择优应用。"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Set

from agent.case_library import search_case_library
from agent.doc_knowledge import format_doc_hits_for_prompt, search_doc_kb
from agent.executor.java_api_controller import (
    DEFAULT_POISSONS_RATIO,
    DEFAULT_THERMAL_K_SOLID,
    DEFAULT_YOUNGS_MODULUS_SOLID,
)
from agent.schemas.analysis import AnalysisReport, EvidenceHit, FixHypothesis
from agent.schemas.task import ExecutionStep, Observation, ReActTaskPlan
from agent.skills import get_skill_injector
from agent.utils.config import get_settings
from agent.utils.llm import LLMClient
from agent.utils.logger import get_logger
from agent.utils.prompt_loader import prompt_loader

logger = get_logger(__name__)


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError("无法从分析响应中提取 JSON")


class AnalysisAgent:
    """多方查阅（skill / 文档库 / 案例库 / 规则 / 计划上下文），产出多角度修复方案。"""

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        *,
        on_usage: Optional[Callable] = None,
        max_hypotheses: int = 4,
    ):
        settings = get_settings()
        backend = settings.llm_backend
        self.llm = llm or LLMClient(
            backend=backend,
            api_key=settings.get_api_key_for_backend(backend),
            base_url=settings.get_base_url_for_backend(backend),
            ollama_url=settings.ollama_url,
            model=settings.get_model_for_backend(backend),
            on_usage=on_usage,
        )
        self.max_hypotheses = max(2, int(max_hypotheses))
        self._tried_keys: Set[str] = set()
        self.last_report: Optional[AnalysisReport] = None

    def reset_tried(self) -> None:
        self._tried_keys.clear()

    def mark_tried(self, hypothesis_id: str) -> None:
        if hypothesis_id:
            self._tried_keys.add(hypothesis_id)

    # ------------------------------------------------------------------ gather
    def gather_evidence(
        self, plan: ReActTaskPlan, observation: Observation
    ) -> List[EvidenceHit]:
        query = " ".join(
            filter(
                None,
                [
                    observation.message or "",
                    plan.user_input or "",
                    "COMSOL 材料 物理场 求解",
                ],
            )
        )[:800]
        hits: List[EvidenceHit] = []

        # 1) 规则层速判
        rule = self._rule_evidence(observation.message or "")
        if rule:
            hits.append(rule)

        # 2) 计划上下文
        hits.extend(self._plan_context_evidence(plan))

        # 3) Skills + API 能力
        try:
            injector = get_skill_injector()
            skills = injector.loader.get_skills_by_triggers(query) or []
            if not skills:
                skills = injector.loader.list_skills()[:3]
            for sk in (skills or [])[:4]:
                hits.append(
                    EvidenceHit(
                        source="skill",
                        title=getattr(sk, "name", "") or "skill",
                        snippet=(
                            getattr(sk, "instructions", "")
                            or getattr(sk, "description", "")
                            or ""
                        )[:600],
                        score=0.7,
                    )
                )
            caps = injector._search_capability_entries(query, limit=3) or []
            for cap in caps:
                hits.append(
                    EvidenceHit(
                        source="api_capability",
                        title=getattr(cap, "title", "") or getattr(cap, "name", ""),
                        snippet=(
                            getattr(cap, "instructions", "")
                            or getattr(cap, "description", "")
                            or ""
                        )[:500],
                        score=0.6,
                    )
                )
        except Exception as exc:
            logger.debug("分析 Agent 查阅 skill/api 失败: %s", exc)

        # 4) 本地 COMSOL 文档库
        try:
            docs = search_doc_kb(query, limit=3) or []
            for d in docs:
                hits.append(
                    EvidenceHit(
                        source="doc_kb",
                        title=str(d.get("title") or d.get("doc_id") or "doc"),
                        snippet=str(d.get("text") or "")[:600],
                        url=str(d.get("source_url") or ""),
                        score=float(d.get("score") or 0.5),
                    )
                )
        except Exception as exc:
            logger.debug("分析 Agent 查阅 doc_kb 失败: %s", exc)

        # 5) 案例库
        try:
            cases = search_case_library(query, limit=3) or []
            for c in cases:
                hits.append(
                    EvidenceHit(
                        source="case_library",
                        title=str(c.get("title") or "case"),
                        snippet=str(c.get("summary") or "")[:500],
                        url=str(c.get("url") or ""),
                        score=0.55,
                    )
                )
        except Exception as exc:
            logger.debug("分析 Agent 查阅案例库失败: %s", exc)

        return hits

    @staticmethod
    def _rule_evidence(message: str) -> Optional[EvidenceHit]:
        msg = message or ""
        lower = msg.lower()
        if "nu" in lower or "泊松" in msg or "线弹性" in msg:
            return EvidenceHit(
                source="rule",
                title="线弹性缺材料属性 nu/E",
                snippet=(
                    "固体力学线弹性材料默认「来自材料」。材料节点必须含泊松比 nu 与杨氏模量 E，"
                    f"否则求解失败。可补齐 E={DEFAULT_YOUNGS_MODULUS_SOLID:g} Pa, nu={DEFAULT_POISSONS_RATIO}。"
                ),
                score=0.95,
            )
        if "材料属性" in msg and ("k" in lower or "导热" in msg):
            return EvidenceHit(
                source="rule",
                title="固体传热缺导热系数 k",
                snippet=(
                    f"固体传热要求材料提供导热系数 k。可补齐 k={DEFAULT_THERMAL_K_SOLID} W/(m·K)。"
                ),
                score=0.9,
            )
        if any(k in msg for k in ("边界", "物理场", "boundary", "feature")):
            return EvidenceHit(
                source="rule",
                title="物理场/边界条件可疑",
                snippet="检查边界特征标签是否为官方可用特征，载荷与约束是否施加在正确边界上。",
                score=0.65,
            )
        if any(k in lower for k in ("mesh", "网格", "element")):
            return EvidenceHit(
                source="rule",
                title="网格相关失败",
                snippet="可尝试放宽最大单元尺寸或改用更稳健的自由四面体/三角形网格。",
                score=0.6,
            )
        if any(k in lower for k in ("solver", "不收敛", "求解", "stationary")):
            return EvidenceHit(
                source="rule",
                title="求解器/研究设置",
                snippet="可回退研究步改为稳态、检查初始值，或简化载荷后重试。",
                score=0.55,
            )
        return None

    @staticmethod
    def _plan_context_evidence(plan: ReActTaskPlan) -> List[EvidenceHit]:
        out: List[EvidenceHit] = []
        mats = []
        if getattr(plan, "material_plan", None):
            for m in getattr(plan.material_plan, "materials", None) or []:
                name = getattr(m, "name", None) or getattr(m, "label", "")
                props = []
                for p in getattr(m, "properties", None) or []:
                    props.append(f"{getattr(p, 'name', '?')}={getattr(p, 'value', '?')}")
                mats.append(f"{name}: {', '.join(props) or '(无显式属性)'}")
        if mats:
            out.append(
                EvidenceHit(
                    source="plan_context",
                    title="当前材料计划",
                    snippet="; ".join(mats)[:700],
                    score=0.8,
                )
            )
        fields = []
        if getattr(plan, "physics_plan", None):
            for f in getattr(plan.physics_plan, "fields", None) or []:
                fields.append(str(getattr(f, "type", f)))
        if fields:
            out.append(
                EvidenceHit(
                    source="plan_context",
                    title="当前物理场计划",
                    snippet=", ".join(fields)[:500],
                    score=0.75,
                )
            )
        done = [
            s.action
            for s in plan.execution_path
            if s.status in ("completed", "warning")
        ]
        if done:
            out.append(
                EvidenceHit(
                    source="plan_context",
                    title="已完成步骤",
                    snippet=" → ".join(done),
                    score=0.5,
                )
            )
        return out

    # ------------------------------------------------------------- hypotheses
    def _rule_hypotheses(self, observation: Observation) -> List[FixHypothesis]:
        msg = observation.message or ""
        lower = msg.lower()
        hyps: List[FixHypothesis] = []

        if "nu" in lower or "泊松" in msg or ("线弹性" in msg and "未定义" in msg):
            hyps.append(
                FixHypothesis(
                    id="rule_elastic_enu",
                    angle="material_property",
                    title="补齐线弹性 E/nu",
                    rationale="求解报线弹性缺 nu/E，材料属性「来自材料」但节点未定义。",
                    sources=["rule"],
                    confidence=0.95,
                    action="update_material_property",
                    parameters={
                        "properties": {
                            "E": DEFAULT_YOUNGS_MODULUS_SOLID,
                            "nu": DEFAULT_POISSONS_RATIO,
                            "youngsmodulus": DEFAULT_YOUNGS_MODULUS_SOLID,
                            "poissonsratio": DEFAULT_POISSONS_RATIO,
                        },
                        "property_group": "Def",
                    },
                )
            )
        if ("材料属性" in msg and ("k" in lower or "导热" in msg)) or re.search(
            r"固体\s*\d*.*材料属性.*[kK]", msg
        ):
            hyps.append(
                FixHypothesis(
                    id="rule_thermal_k",
                    angle="material_property",
                    title="补齐导热系数 k",
                    rationale="固体传热缺材料属性 k。",
                    sources=["rule"],
                    confidence=0.92,
                    action="update_material_property",
                    parameters={
                        "properties": {"k": DEFAULT_THERMAL_K_SOLID},
                        "property_group": "Def",
                    },
                )
            )
        if any(k in msg for k in ("边界", "物理场")) and "材料属性" not in msg:
            hyps.append(
                FixHypothesis(
                    id="rule_physics_rollback",
                    angle="boundary",
                    title="回退并重建物理场边界",
                    rationale="错误指向物理场/边界，回退到 add_physics 用更稳妥的约束与载荷。",
                    sources=["rule"],
                    confidence=0.55,
                    action="rollback_physics",
                    parameters={
                        "physics_input": (
                            "保持现有物理场类型；使用官方可用边界特征；"
                            "固体力学：底面固定，另一面施加合理载荷；"
                            "传热：设定合理温度/热通量边界。"
                        )
                    },
                )
            )
        if any(k in lower for k in ("mesh", "网格")):
            hyps.append(
                FixHypothesis(
                    id="rule_mesh_coarser",
                    angle="mesh",
                    title="放宽网格尺寸后重试",
                    rationale="网格相关失败时可先用更粗网格保证可算。",
                    sources=["rule"],
                    confidence=0.5,
                    action="rollback_mesh",
                    parameters={"mesh": {"max_element_size": 0.1}},
                )
            )
        return hyps

    def _llm_hypotheses(
        self,
        plan: ReActTaskPlan,
        observation: Observation,
        evidence: List[EvidenceHit],
        seed: List[FixHypothesis],
    ) -> List[FixHypothesis]:
        current = plan.get_current_step()
        completed = [
            s.action for s in plan.execution_path if s.status in ("completed", "warning")
        ]
        tried = sorted(self._tried_keys) or ["(无)"]
        evidence_lines = []
        for e in evidence[:10]:
            evidence_lines.append(
                f"- [{e.source}] {e.title}: {e.snippet[:280]}"
                + (f" ({e.url})" if e.url else "")
            )
        if not evidence_lines:
            evidence_lines.append("- (未检索到额外资料，请依据错误信息与 COMSOL 常识分析)")
        # 附上文档库格式化摘要（若有）
        try:
            doc_hits = [e for e in evidence if e.source == "doc_kb"]
            if doc_hits:
                raw = [
                    {
                        "title": e.title,
                        "text": e.snippet,
                        "source_url": e.url,
                        "doc_id": e.title,
                    }
                    for e in doc_hits
                ]
                block = format_doc_hits_for_prompt(raw)
                if block:
                    evidence_lines.append(block)
        except Exception:
            pass

        try:
            prompt = prompt_loader.format(
                "react",
                "error_analysis",
                error_message=observation.message or "",
                user_input=plan.user_input or "",
                current_step=(
                    f"{current.action}/{current.step_type}" if current else "(unknown)"
                ),
                completed_actions=" → ".join(completed) or "(无)",
                tried_fixes=", ".join(tried),
                evidence_block="\n".join(evidence_lines),
            )
        except Exception:
            prompt = (
                f"分析 COMSOL 错误并给出多个修复 JSON。\n错误:{observation.message}\n"
                f"需求:{plan.user_input}\n资料:\n" + "\n".join(evidence_lines)
            )

        try:
            response = self.llm.call(prompt, temperature=0.2, max_retries=2)
            data = _extract_json(response)
        except Exception as exc:
            logger.warning("分析 Agent LLM 假设失败，仅用规则假设: %s", exc)
            return seed

        out: List[FixHypothesis] = list(seed)
        seen = {h.id for h in out}
        for item in data.get("hypotheses") or []:
            if not isinstance(item, dict):
                continue
            hid = str(item.get("id") or "").strip() or f"llm_{len(out)+1}"
            if hid in seen:
                continue
            try:
                hyp = FixHypothesis(
                    id=hid,
                    angle=str(item.get("angle") or "general"),
                    title=str(item.get("title") or hid),
                    rationale=str(item.get("rationale") or ""),
                    sources=[str(s) for s in (item.get("sources") or [])],
                    confidence=float(item.get("confidence") or 0.5),
                    action=item.get("action") or "modify_parameters",
                    parameters=dict(item.get("parameters") or {}),
                )
            except Exception:
                continue
            out.append(hyp)
            seen.add(hid)
            if len(out) >= self.max_hypotheses:
                break

        # 把 LLM 的摘要挂到 seed 报告侧，由 analyze 读取 data
        self._last_llm_meta = {
            "error_summary": str(data.get("error_summary") or ""),
            "root_cause_hypothesis": str(data.get("root_cause_hypothesis") or ""),
        }
        return out

    # ---------------------------------------------------------------- analyze
    def analyze(
        self, plan: ReActTaskPlan, observation: Observation
    ) -> AnalysisReport:
        """查阅多方资料，生成多角度假设并选定下一个未尝试角度。"""
        evidence = self.gather_evidence(plan, observation)
        seed = self._rule_hypotheses(observation)
        self._last_llm_meta: Dict[str, str] = {}
        hyps = self._llm_hypotheses(plan, observation, evidence, seed)

        # 标记已尝试
        for h in hyps:
            if h.id in self._tried_keys:
                h.tried = True
        hyps.sort(key=lambda h: (h.tried, -h.confidence))

        selected = next((h for h in hyps if not h.tried), None)
        meta = getattr(self, "_last_llm_meta", {}) or {}
        report = AnalysisReport(
            error_summary=meta.get("error_summary")
            or (observation.message or "")[:200],
            root_cause_hypothesis=meta.get("root_cause_hypothesis")
            or (selected.rationale if selected else ""),
            evidence=evidence,
            hypotheses=hyps,
            selected_hypothesis_id=selected.id if selected else None,
            notes=f"已尝试 {len(self._tried_keys)} 个角度；本次候选 {len(hyps)} 个。",
        )
        self.last_report = report
        logger.info(
            "AnalysisAgent: evidence=%s hypotheses=%s selected=%s",
            len(evidence),
            len(hyps),
            report.selected_hypothesis_id,
        )
        return report

    # ----------------------------------------------------------------- apply
    def apply(
        self, plan: ReActTaskPlan, hypothesis: FixHypothesis
    ) -> Optional[ReActTaskPlan]:
        """把选定假设落到计划上；成功则标记为已尝试。"""
        if not hypothesis or hypothesis.tried:
            return None
        action = hypothesis.action
        params = dict(hypothesis.parameters or {})
        idx = plan.current_step_index

        if action == "reorchestrate":
            from agent.react.iteration_controller import REORCHESTRATE_PREFIX

            plan.status = "failed"
            plan.error = REORCHESTRATE_PREFIX + (
                hypothesis.rationale or hypothesis.title or "分析 Agent 建议重新编排"
            )
            self.mark_tried(hypothesis.id)
            return plan

        if action == "update_material_property":
            if idx < 0 or idx >= len(plan.execution_path):
                return None
            # 避免重复注入同一 fix id
            for step in plan.execution_path:
                if getattr(step, "step_id", "") == f"step_analysis_{hypothesis.id}":
                    self.mark_tried(hypothesis.id)
                    return None
            fix_step = ExecutionStep(
                step_id=f"step_analysis_{hypothesis.id}",
                step_type="material",
                action="update_material_property",
                parameters={
                    "properties": params.get("properties")
                    or {"nu": DEFAULT_POISSONS_RATIO, "E": DEFAULT_YOUNGS_MODULUS_SOLID},
                    "property_group": params.get("property_group") or "Def",
                    "material_names": params.get("material_names"),
                },
                status="pending",
            )
            plan.execution_path.insert(idx, fix_step)
            plan.execution_path[idx + 1].status = "pending"
            plan.execution_path[idx + 1].result = None
            self.mark_tried(hypothesis.id)
            return plan

        if action in (
            "rollback_material",
            "rollback_physics",
            "rollback_mesh",
            "rollback_study",
        ):
            target_type = {
                "rollback_material": "material",
                "rollback_physics": "physics",
                "rollback_mesh": "mesh",
                "rollback_study": "study",
            }[action]
            target_index = None
            for i, step in enumerate(plan.execution_path):
                if step.step_type == target_type:
                    target_index = i
                    break
            if target_index is None:
                return None
            for i in range(target_index, len(plan.execution_path)):
                plan.execution_path[i].status = "pending"
                plan.execution_path[i].result = None
                if i == target_index:
                    step = plan.execution_path[i]
                    if params.get("material_input") and step.step_type == "material":
                        step.parameters["material_input"] = params["material_input"]
                    if params.get("physics_input") and step.step_type == "physics":
                        step.parameters["physics_input"] = params["physics_input"]
                    if params.get("mesh") and step.step_type == "mesh":
                        step.parameters.update(params.get("mesh") or {})
                        if isinstance(params.get("mesh"), dict):
                            step.parameters["mesh"] = params["mesh"]
                    if params.get("study_input") and step.step_type == "study":
                        step.parameters["study_input"] = params["study_input"]
            plan.current_step_index = target_index
            self.mark_tried(hypothesis.id)
            return plan

        if action in ("inject_step", "modify_parameters"):
            # 修改当前失败步或指定 step 的参数后重试
            target = plan.get_current_step()
            step_id = params.get("step_id")
            if step_id:
                for step in plan.execution_path:
                    if step.step_id == step_id:
                        target = step
                        break
            if not target:
                return None
            for key in (
                "material_input",
                "physics_input",
                "geometry_input",
                "study_input",
                "mesh",
            ):
                if key in params:
                    target.parameters[key] = params[key]
            extra = params.get("parameters")
            if isinstance(extra, dict):
                target.parameters.update(extra)
            target.status = "pending"
            target.result = None
            # 若目标不是当前步，回退索引
            for i, step in enumerate(plan.execution_path):
                if step.step_id == target.step_id:
                    plan.current_step_index = i
                    for j in range(i, len(plan.execution_path)):
                        plan.execution_path[j].status = "pending"
                        plan.execution_path[j].result = None
                    break
            self.mark_tried(hypothesis.id)
            return plan

        return None

    def analyze_and_apply(
        self, plan: ReActTaskPlan, observation: Observation
    ) -> Optional[ReActTaskPlan]:
        """分析并应用下一个未尝试角度；无可用角度时返回 None。"""
        report = self.analyze(plan, observation)
        hyp = report.selected()
        if not hyp:
            logger.info("AnalysisAgent: 无剩余可尝试角度")
            return None
        updated = self.apply(plan, hyp)
        if updated is None:
            return None
        return updated
