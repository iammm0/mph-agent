"""PromptManager：模板目录扫描、get_template/get_chain、变量替换（{{name}} 与 .format 兼容）。"""
from pathlib import Path
from typing import Dict, List, Optional, Any

# 内联默认模板（无外部文件时也可运行）；文件模板覆盖同名项；占位符与 prompts/*.txt 一致
DEFAULT_TEMPLATES: Dict[str, str] = {
    "planner/geometry_planner": """几何建模助手。将用户描述转为 JSON。支持 rectangle/circle/ellipse，position 含 x,y，单位默认 m。用户输入：{user_input} 请只输出 JSON。""",
    "planner/physics_planner": """物理场助手。将用户描述转为 JSON。支持 heat/electromagnetic/structural/fluid。用户输入：{user_input} 请只输出 JSON。""",
    "planner/study_planner": """研究类型助手。将用户描述转为 JSON。支持 stationary/time_dependent/eigenvalue/frequency。用户输入：{user_input} 请只输出 JSON。""",
    "react/reasoning": """你是一位 COMSOL 建模规划助手。请根据用户需求，按 COMSOL 实际建模流程给出**具体**规划，不要原样复述用户提示词。

用户需求：{user_input}
会话记忆（如有）：{memory_context}

请按以下顺序具体说明并输出 JSON：
1. 几何：创建什么样的几何模型（形状、尺寸、单位，如“长方体 1m×0.5m×0.2m”、“二维矩形 0.1m×0.05m”等）。
2. 材料：在哪些域/位置添加什么材料；若涉及固体力学/线弹性，需明确杨氏模量 E、泊松比 nu 等。
3. 物理场：添加什么物理场（热、固体力学、流体等），边界/载荷如何设置。
4. 网格：生成何种网格（自由四面体/三角形、尺寸或单元数等）。
5. 研究：配置何种研究（稳态/瞬态/特征值等）及求解思路。

请严格以 JSON 格式返回且仅返回一个 JSON 对象，不要其他文字：
{{
  "task_type": "full 或 geometry/physics/study",
  "required_steps": ["create_geometry", "add_material", "add_physics", "generate_mesh", "configure_study", "solve"],
  "stop_after_step": "执行到该步后保存 .mph 并结束，取值 create_geometry/add_material/add_physics/generate_mesh/configure_study/solve；不填或 solve 表示完整流程",
  "parameters": {{
    "geometry_input": "具体几何描述，如：创建 3D 长方体，长宽高 1m、0.5m、0.2m",
    "material_input": "具体材料描述，如：全部域分配钢材；线弹性需 E=200e9 Pa、nu=0.3",
    "physics_input": "具体物理场与边界，如：固体力学，底面固定，顶面施加 1e6 Pa 压力",
    "mesh": {{ "max_element_size": 0.05 }},
    "study_input": "稳态研究，求解"
  }},
  "plan_description": "一段完整的具体规划说明：创建何种几何、在哪些地方添加什么材料、添加什么物理场、生成什么网格、配置什么研究与求解思路。用于展示给用户，不要笼统复述需求。",
  "clarifying_questions": ["问题 1", "问题 2"],
  "case_library_suggestions": []
}}""",
    "react/planning": """根据当前状态规划下一步。模型：{model_name} 需求：{user_input} 已完成：{completed_steps} 当前步骤：{current_step} 观察：{observations} 以 JSON 返回 action, reasoning, parameters, expected_result。""",
    "react/validation": """验证建模计划。计划 JSON：{plan_json} 以 JSON 返回 valid, errors, warnings, suggestions。""",
}


class PromptManager:
    """
    统一模板与链式提示词管理。
    - get_template(name): name 为 "category/name"，从目录或内联默认加载
    - get_chain(name): 多段链拼接（内存配置），可选
    - 变量替换：format 使用 .format(**kwargs)，模板中 {{ 表示字面量 {
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        if prompts_dir is None:
            prompts_dir = Path(__file__).parent.parent.parent / "prompts"
        self.prompts_dir = Path(prompts_dir)
        self._cache: Dict[str, str] = {}
        self._chains: Dict[str, List[str]] = {}  # chain_name -> list of template names
        self._scan_templates()

    def _scan_templates(self) -> None:
        """扫描 prompts 子目录，注册 category/name -> 内容。"""
        if not self.prompts_dir.exists():
            return
        for sub in self.prompts_dir.iterdir():
            if sub.is_dir():
                category = sub.name
                for f in sub.glob("*.txt"):
                    name = f.stem
                    key = f"{category}/{name}"
                    try:
                        self._cache[key] = f.read_text(encoding="utf-8")
                    except Exception:
                        pass

    def get_template(self, name: str) -> str:
        """
        获取模板正文。name 格式为 "category/name"（如 "planner/geometry_planner"）。
        先查文件缓存，再查内联默认。
        """
        if name in self._cache:
            return self._cache[name]
        if name in DEFAULT_TEMPLATES:
            return DEFAULT_TEMPLATES[name]
        raise FileNotFoundError(f"Prompt 模板不存在: {name}")

    def load(self, category: str, name: str) -> str:
        """兼容旧接口：按 category 与 name 加载，等价于 get_template(f\"{category}/{name}\")。"""
        return self.get_template(f"{category}/{name}")

    def format(self, category: str, name: str, **kwargs: Any) -> str:
        """加载并格式化：先 get_template(category/name)，再 .format(**kwargs)。"""
        template = self.load(category, name)
        return template.format(**kwargs)

    def format_template(self, name: str, **kwargs: Any) -> str:
        """按全名 name 加载并格式化。"""
        template = self.get_template(name)
        return template.format(**kwargs)

    def register_chain(self, chain_name: str, template_names: List[str]) -> None:
        """注册一条链：多段模板按顺序拼接。"""
        self._chains[chain_name] = list(template_names)

    def get_chain(self, chain_name: str, **kwargs: Any) -> str:
        """
        获取链式提示词：多段模板用双换行拼接，每段做变量替换。
        若未注册该链，则退化为 get_template(chain_name)。
        """
        if chain_name in self._chains:
            parts = [
                self.get_template(tn).format(**kwargs)
                for tn in self._chains[chain_name]
            ]
            return "\n\n".join(parts)
        return self.get_template(chain_name).format(**kwargs)

    def list_templates(self) -> List[str]:
        """列出已加载的模板名（含内联默认）。"""
        keys = set(DEFAULT_TEMPLATES) | set(self._cache)
        return sorted(keys)


# 单例，与 prompt_loader 对齐：由 prompts_dir 相对于项目根解析
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(prompts_dir: Optional[Path] = None) -> PromptManager:
    """获取 PromptManager 单例。"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager(prompts_dir=prompts_dir)
    return _prompt_manager
