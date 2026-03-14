"""Skills 单元测试：SkillLoader 解析、SkillInjector 注入。"""
import pytest
from pathlib import Path

from agent.skills.loader import SkillLoader, Skill, _parse_skill_md
from agent.skills.injector import SkillInjector, MARKER


class TestParseSkillMd:
    """SKILL.md 解析（frontmatter + body）"""

    def test_with_frontmatter(self):
        content = """---
name: foo
description: bar
tags: [a, b]
---
# 正文
hello world
"""
        fm, body = _parse_skill_md(content)
        assert fm.get("name") == "foo"
        assert fm.get("description") == "bar"
        assert "正文" in body
        assert "hello world" in body

    def test_without_frontmatter(self):
        content = "no frontmatter\njust body"
        fm, body = _parse_skill_md(content)
        assert fm == {}
        assert "no frontmatter" in body


class TestSkillLoader:
    """SkillLoader：扫描 skills 目录、按 name/tag/triggers 查询"""

    def test_list_skills(self):
        # 使用项目真实 skills 目录（若存在）
        root = Path(__file__).parent.parent / "skills"
        if not root.exists():
            pytest.skip("skills/ 目录不存在")
        loader = SkillLoader(roots=[root])
        skills = loader.list_skills()
        assert isinstance(skills, list)
        for s in skills:
            assert isinstance(s, Skill)
            assert s.name
            assert hasattr(s, "instructions")
            assert hasattr(s, "triggers")

    def test_get_skill_by_name(self):
        root = Path(__file__).parent.parent / "skills"
        if not root.exists():
            pytest.skip("skills/ 目录不存在")
        loader = SkillLoader(roots=[root])
        # 至少有一个 comsol-basics
        skill = loader.get_skill("comsol-basics")
        if skill:
            assert "矩形" in skill.instructions or "rectangle" in skill.instructions.lower()

    def test_get_skills_by_triggers(self):
        root = Path(__file__).parent.parent / "skills"
        if not root.exists():
            pytest.skip("skills/ 目录不存在")
        loader = SkillLoader(roots=[root])
        skills = loader.get_skills_by_triggers("创建一个矩形，几何")
        assert isinstance(skills, list)
        # 命中 trigger 的应排在前面
        if skills:
            assert any("几何" in s.instructions or "矩形" in s.instructions for s in skills)


class TestSkillInjector:
    """SkillInjector：按 query 匹配技能并注入到 prompt"""

    def test_inject_into_prompt_with_loader(self):
        root = Path(__file__).parent.parent / "skills"
        if not root.exists():
            pytest.skip("skills/ 目录不存在")
        loader = SkillLoader(roots=[root])
        injector = SkillInjector(loader=loader, top_k=2)
        user_prompt = "用户输入：画一个矩形"
        out = injector.inject_into_prompt("画一个矩形", user_prompt)
        assert MARKER in out
        assert "用户输入" in out
        # 应包含技能正文或至少标记
        assert out.strip().startswith(MARKER) or MARKER in out

    def test_inject_into_prompt_empty_loader(self):
        loader = SkillLoader(roots=[])  # 空根目录，无技能
        injector = SkillInjector(loader=loader, top_k=2)
        user_prompt = "hello"
        out = injector.inject_into_prompt("hello", user_prompt)
        assert out == user_prompt

    def test_last_used_skills(self):
        root = Path(__file__).parent.parent / "skills"
        if not root.exists():
            pytest.skip("skills/ 目录不存在")
        injector = SkillInjector(loader=SkillLoader(roots=[root]), top_k=2)
        injector.inject_into_prompt("几何 矩形", "prompt")
        names = injector.last_used_skills()
        assert isinstance(names, list)
