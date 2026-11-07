"""路由：根据用户输入决定走 Q&A 还是技术/执行流（Planner → Core → Summary）。
使用 DeepSeek deepseek-flash 模型做意图分类；若未配置或调用失败则回退到关键字规则。"""
from typing import Literal

RouteResult = Literal["qa", "technical"]

# 回退用：问候/再见 -> Q&A
_GREETING_KEYWORDS = ["你好", "嗨", "hello", "hi", "再见", "bye", "谢谢", "感谢", "帮助", "help"]
# 回退用：操作类动词 -> technical
_TECHNICAL_KEYWORDS = ["创建", "建", "画", "添加", "执行", "分析", "扫描", "生成", "建模", "几何", "物理", "网格", "求解", "研究", "create", "add", "build", "run", "solve", "model"]

_ROUTE_PROMPT = """你是一个意图分类器。根据用户输入，判断应走「通用问答」还是「技术/建模执行」流程。

规则：
- 通用问答(qa)：打招呼、致谢、一般性帮助、与 COMSOL/建模无关的闲聊或简单问题。
- 技术/建模(technical)：涉及创建/修改 COMSOL 模型、几何、物理场、网格、研究、求解等具体建模或执行需求。

只输出一个词：qa 或 technical。不要解释，不要换行。"""


def _route_by_keywords(user_input: str) -> RouteResult:
    """关键字规则回退。"""
    text = (user_input or "").strip().lower()
    if not text:
        return "qa"
    for w in _GREETING_KEYWORDS:
        if w in text and len(text) < 80:
            return "qa"
    for w in _TECHNICAL_KEYWORDS:
        if w in text:
            return "technical"
    if len(text) < 30:
        return "qa"
    return "technical"


def _route_by_deepseek(user_input: str) -> RouteResult:
    """使用 DeepSeek deepseek-flash 做意图分类。"""
    try:
        from agent.utils.config import get_settings
        from agent.utils.llm import LLMClient
    except ImportError:
        return _route_by_keywords(user_input)

    settings = get_settings()
    api_key = settings.get_api_key_for_backend("deepseek") or settings.deepseek_api_key
    if not (api_key and api_key.strip()):
        return _route_by_keywords(user_input)

    try:
        client = LLMClient(backend="deepseek", api_key=api_key.strip())
        prompt = f"{_ROUTE_PROMPT}\n\n用户输入：\n{user_input}"
        reply = client.call(
            prompt,
            model="deepseek-flash",
            temperature=0,
            max_retries=1,
        )
        if not reply:
            return _route_by_keywords(user_input)
        text = reply.strip().lower()
        if "technical" in text:
            return "technical"
        if "qa" in text:
            return "qa"
        # 无法解析时按长度倾向 technical，避免把建模需求误判为 qa
        return "technical"
    except Exception:
        return _route_by_keywords(user_input)


def route(user_input: str) -> RouteResult:
    """
    根据用户输入返回 "qa" 或 "technical"。
    优先使用 DeepSeek deepseek-flash 做意图判断；未配置或失败时使用关键字规则。
    """
    if not (user_input or "").strip():
        return "qa"
    return _route_by_deepseek(user_input)
