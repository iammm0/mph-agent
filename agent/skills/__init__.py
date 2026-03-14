"""技能/插件系统：SKILL.md 加载与按需注入，供推理与行动时采纳隐性知识。"""
from typing import Optional

from agent.skills.loader import SkillLoader, Skill
from agent.skills.injector import SkillInjector
from agent.skills.vector_store import SkillVectorStore, get_default_embedder
from agent.skills.api_catalog_builder import build_api_capability_entries, ApiCapabilityEntry

__all__ = [
    "SkillLoader",
    "Skill",
    "SkillInjector",
    "SkillVectorStore",
    "get_default_embedder",
    "get_skill_injector",
    "build_api_capability_entries",
    "ApiCapabilityEntry",
]

_injector: Optional[SkillInjector] = None


def get_skill_injector(
    loader: Optional[SkillLoader] = None,
    vector_store: Optional[SkillVectorStore] = None,
    top_k: int = 5,
) -> SkillInjector:
    """返回全局 SkillInjector 单例，供推理/规划/执行时注入隐性知识。若未传 vector_store 且已安装 vec 可选依赖，则自动创建并启用向量检索。"""
    global _injector
    if _injector is None:
        if vector_store is None:
            try:
                emb = get_default_embedder()
                if emb is not None:
                    vector_store = SkillVectorStore(embedder=emb)
            except Exception:
                vector_store = None
        _injector = SkillInjector(loader=loader, vector_store=vector_store, top_k=top_k)
    return _injector
