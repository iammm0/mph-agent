"""按需注入：根据 query 匹配技能，将隐性知识注入到 prompt，供推理与行动时采纳。"""
from typing import List, Optional

from agent.skills.loader import SkillLoader, Skill
from agent.skills.vector_store import SkillVectorStore
from agent.skills.api_catalog_builder import build_api_capability_entries, ApiCapabilityEntry

MARKER = "=== RELEVANT SKILLS (请采纳以下隐性知识) ==="


class SkillInjector:
    """
    根据用户 query 优先做向量检索（VSS），其次 triggers/tags 匹配，取 Top-K 技能，
    将 instructions 作为隐性知识注入到 prompt 中，供 Agent 推理与行动时读取并采纳。
    支持：inject(system_prompt) 与 inject_into_prompt(query, user_prompt)。
    """

    def __init__(
        self,
        loader: Optional[SkillLoader] = None,
        vector_store: Optional[SkillVectorStore] = None,
        top_k: int = 5,
    ):
        self.loader = loader or SkillLoader()
        self.vector_store = vector_store
        self.top_k = max(1, top_k)
        self._last_used: List[str] = []
        # 懒加载：官方 API 能力表条目，仅在需要时构建一次
        self._api_entries: Optional[List[ApiCapabilityEntry]] = None

    def _get_api_entries(self) -> List[ApiCapabilityEntry]:
        """懒加载官方 API 能力表（基于 JavaAPIController._official_api_wrappers）。"""
        if self._api_entries is None:
            try:
                self._api_entries = build_api_capability_entries()
            except Exception:
                self._api_entries = []
        return self._api_entries or []

    def get_api_capability_docs(self) -> List[Skill]:
        """
        将官方 API 能力条目视作“虚拟技能”，用于向量检索与注入。
        注意：这里只构造内存中的 Skill 对象，不写 SKILL.md 文件。
        """
        entries = self._get_api_entries()
        skills: List[Skill] = []
        for e in entries:
            skills.append(
                Skill(
                    name=e.name,
                    description=e.title,
                    instructions=e.instructions,
                    version=None,
                    author=None,
                    tags=["comsol-api", "java-api"],
                    triggers=[],
                    prerequisites=[],
                    path=None,
                )
            )
        return skills

    def _get_skills_block(self, query: str) -> tuple[str, List[str]]:
        """根据 query 优先向量检索，否则 triggers/tags 匹配，返回 (拼接后的正文, 使用的技能名列表)。"""
        block_parts: List[str] = []
        names_used: List[str] = []

        # 1) 向量检索（若已配置且 DB 有数据）
        if self.vector_store and query:
            # 1.1 动态构造：普通技能 + 官方 API 能力表虚拟技能
            all_skills: List[Skill] = self.loader.list_skills() + self.get_api_capability_docs()
            self.vector_store.ensure_indexed(all_skills)
            hits = self.vector_store.search(query, top_k=self.top_k)
            if hits:
                for name, content, _ in hits:
                    if content and name not in names_used:
                        block_parts.append(content)
                        names_used.append(name)
                if block_parts:
                    self._last_used = names_used
                    return "\n\n".join(block_parts), self._last_used

        # 2) 回退：trigger / tag 匹配
        skills = self.loader.get_skills_by_triggers(query)
        if not skills:
            skills = self.loader.list_skills()[: self.top_k]
        else:
            skills = skills[: self.top_k]
        if not skills:
            return "", []
        self._last_used = [s.name for s in skills]
        block = "\n\n".join(s.instructions for s in skills if s.instructions and s.instructions.strip())
        return block, self._last_used

    def inject(self, query: str, system_prompt: str) -> str:
        """
        在调用 LLM 前调用：返回增强后的 system_prompt（末尾追加技能块）。
        """
        block, _ = self._get_skills_block(query)
        if not block:
            return system_prompt
        return f"{system_prompt}\n\n{MARKER}\n{block}"

    def inject_into_prompt(self, query: str, user_prompt: str) -> str:
        """
        将匹配到的技能作为隐性知识拼接到 user_prompt 前部；
        当 LLM 仅接受单条 user 消息时使用，推理与行动时均可采纳。
        """
        block, _ = self._get_skills_block(query)
        if not block:
            return user_prompt
        return f"{MARKER}\n{block}\n\n---\n\n{user_prompt}"

    def last_used_skills(self) -> List[str]:
        """返回本轮注入使用的技能名，便于日志与统计。"""
        return list(self._last_used)
