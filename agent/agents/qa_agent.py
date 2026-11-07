"""Q&A Agent：仅对话、介绍、帮助，不调用工具。"""
from typing import Optional, Any, Callable

from agent.core.base import BaseAgent
from agent.utils.llm import LLMClient
from agent.utils.config import get_settings
from agent.utils.logger import get_logger

logger = get_logger(__name__)


class QAAgent(BaseAgent):
    """轻量 Q&A：只做对话与帮助，响应快、成本低。"""

    def _default_system_prompt(self) -> str:
        return (
            "你是 COMSOL Multiphysics 建模助手。"
            "回答用户关于 COMSOL 的简介、帮助、概念问题。"
            "若用户需要实际创建模型或执行操作，请建议他们直接描述建模需求。"
        )

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        history: Optional[list] = None,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
        on_usage: Optional[Callable] = None,
    ):
        super().__init__(system_prompt=system_prompt, history=history)
        settings = get_settings()
        backend = backend or settings.llm_backend
        self.llm = LLMClient(
            backend=backend,
            api_key=api_key or settings.get_api_key_for_backend(backend),
            base_url=base_url or settings.get_base_url_for_backend(backend),
            ollama_url=ollama_url or settings.ollama_url,
            model=model or settings.get_model_for_backend(backend),
            on_usage=on_usage,
        )

    def process(self, user_input: str, **kwargs: Any) -> str:
        """仅做对话回复，不调用工具。"""
        logger.debug("Q&A 处理: %s", user_input[:80])
        prompt = f"{self.system_prompt}\n\n用户: {user_input}\n\n助手:"
        reply = self.llm.call(prompt, temperature=0.7)
        return (reply or "").strip()

    def process_stream(
        self,
        user_input: str,
        *,
        on_chunk: Callable[[str], None],
        on_reasoning_chunk: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """流式对话回复，同时返回完整文本。"""
        logger.debug("Q&A 流式处理: %s", user_input[:80])
        prompt = f"{self.system_prompt}\n\n用户: {user_input}\n\n助手:"
        reply = self.llm.call_stream(
            prompt,
            temperature=0.7,
            on_chunk=on_chunk,
            on_reasoning_chunk=on_reasoning_chunk,
        )
        return (reply or "").strip()
