"""从 JavaAPIController._official_api_wrappers 构建官方 API 能力表文档，供向量检索与技能注入使用。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any

from agent.executor.java_api_controller import JavaAPIController


@dataclass
class ApiCapabilityEntry:
    """官方 API 能力条目：用于向量库与技能系统。"""

    name: str
    title: str
    description: str
    wrapper_name: str
    owner: str
    method_name: str

    @property
    def instructions(self) -> str:
        """
        转为 Skill-like 文本块，用于向量检索与 Prompt 注入。

        结构示例：
        [删除研究节点] api_model_study_remove
        所属类: com.comsol.model.Study
        方法: remove(String tag)

        用途: 删除给定标签的研究节点。
        wrapper_name: api_model_study_remove
        owner: com.comsol.model.Study
        method_name: remove
        """
        lines = [
            f"[{self.title}] {self.wrapper_name}",
            f"所属类: {self.owner}",
            f"方法: {self.method_name}",
        ]
        if self.description:
            lines.append("")
            lines.append(f"用途: {self.description}")
        lines.append("")
        lines.append(f"wrapper_name: {self.wrapper_name}")
        lines.append(f"owner: {self.owner}")
        lines.append(f"method_name: {self.method_name}")
        return "\n".join(lines).strip()


def _guess_title(owner: str, method_name: str) -> str:
    """
    根据 owner + method_name 粗略生成一个中文/英文标题，便于人类浏览与语义检索。
    这里仅做简单拆词与映射，后续可按需替换/增强。
    """
    lower = method_name.lower()
    if "remove" in lower or "delete" in lower:
        if "study" in owner.lower():
            return "删除研究节点"
        if "material" in owner.lower():
            return "删除材料节点"
        if "physics" in owner.lower():
            return "删除物理场节点"
        if "selection" in owner.lower():
            return "删除选择集"
        return "删除节点/对象"
    if "clear" in lower:
        return "清除数据/节点"
    if "create" in lower:
        return "创建节点/对象"
    if "export" in lower or "save" in lower:
        return "导出结果/数据"
    if "measure" in lower:
        return "几何测量"
    if "run" in lower or "solve" in lower:
        return "运行/求解"
    return f"{owner.split('.')[-1]}.{method_name}"


def build_api_capability_entries() -> List[ApiCapabilityEntry]:
    """
    从 JavaAPIController 的官方 API 元数据构建能力条目列表。
    仅依赖已加载的 comsol_official_api_wrappers 元信息，不触发网络抓取。
    """
    ctrl = JavaAPIController()
    items: List[Dict[str, Any]] = ctrl.list_official_api_wrappers(limit=10_000).get("items", [])
    entries: List[ApiCapabilityEntry] = []
    for item in items:
        wrapper = item.get("wrapper_name") or ""
        owner = item.get("owner") or ""
        method_name = item.get("method_name") or ""
        if not wrapper or not owner or not method_name:
            continue
        title = _guess_title(owner, method_name)
        desc = ""
        entries.append(
            ApiCapabilityEntry(
                name=wrapper,
                title=title,
                description=desc,
                wrapper_name=wrapper,
                owner=owner,
                method_name=method_name,
            )
        )
    return entries

