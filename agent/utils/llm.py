"""LLM 客户端 — 通过 LiteLLM 统一接入多提供商，不再自维护各后端 HTTP 细节。"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from agent.utils.logger import get_logger

logger = get_logger(__name__)

_SUPPORTED_BACKENDS = ("deepseek", "kimi", "ollama", "openai-compatible")
RuntimeBackend = Literal["deepseek", "kimi", "ollama", "openai-compatible"]


def _ensure_litellm():
    try:
        import litellm  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("litellm 未安装，请运行: uv sync / pip install litellm") from exc
    # 桌面应用场景：关闭遥测，避免额外网络请求
    litellm.telemetry = False
    litellm.suppress_debug_info = True
    return litellm


def _with_prefix(model: str, prefix: str) -> str:
    name = (model or "").strip()
    if not name:
        return f"{prefix}/"
    if "/" in name:
        return name
    return f"{prefix}/{name}"


def resolve_litellm_model(backend: RuntimeBackend, model: str) -> str:
    """把运行时 backend + 用户模型名映射为 LiteLLM model id。"""
    if backend == "deepseek":
        return _with_prefix(model, "deepseek")
    if backend == "kimi":
        return _with_prefix(model, "moonshot")
    if backend == "ollama":
        return _with_prefix(model, "ollama")
    # 任意 OpenAI 兼容网关：用 openai/ 前缀 + api_base
    return _with_prefix(model, "openai")


def _chunk_text(chunk: Any) -> str:
    try:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) if delta is not None else None
        if content:
            return str(content)
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message is not None else None
        return str(content) if content else ""
    except Exception:
        return ""


def _response_text(response: Any) -> str:
    try:
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message is not None else None
        return str(content) if content else ""
    except Exception:
        return ""


class LLMClient:
    """LLM 客户端封装 — 底层统一走 LiteLLM。"""

    def __init__(
        self,
        backend: RuntimeBackend = "ollama",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        if backend not in _SUPPORTED_BACKENDS:
            raise ValueError(
                f"不支持的后端: {backend}，支持: {', '.join(_SUPPORTED_BACKENDS)}"
            )

        self.backend_type: RuntimeBackend = backend
        self.api_key = (api_key or "").strip() or None
        self.base_url = (base_url or "").strip().rstrip("/") or None
        self.ollama_url = (ollama_url or base_url or "http://localhost:11434").rstrip("/")

        if backend == "deepseek":
            if not self.api_key:
                raise ValueError("使用 deepseek 后端需要提供 api_key")
            self.default_model = model or "deepseek-reasoner"
        elif backend == "kimi":
            if not self.api_key:
                raise ValueError("使用 kimi 后端需要提供 api_key")
            self.default_model = model or "moonshot-v1-8k"
        elif backend == "openai-compatible":
            if not self.api_key:
                raise ValueError("使用 openai-compatible 后端需要提供 api_key")
            if not self.base_url:
                raise ValueError("使用 openai-compatible 后端需要提供 base_url")
            self.default_model = model or "gpt-3.5-turbo"
        else:
            self.default_model = model or "llama3"

        # 兼容旧代码：部分路径仍访问 client.backend
        self.backend = self
        logger.info(
            "LLM 客户端已初始化 (LiteLLM): %s, 模型: %s",
            backend,
            self.default_model,
        )

    def _completion_kwargs(
        self,
        *,
        prompt: str,
        model: str,
        temperature: float,
        stream: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": resolve_litellm_model(self.backend_type, model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": stream,
            "num_retries": 0,  # 外层已控制重试
        }
        if self.backend_type == "ollama":
            kwargs["api_base"] = self.ollama_url
        elif self.backend_type == "openai-compatible":
            kwargs["api_base"] = self.base_url
            kwargs["api_key"] = self.api_key
        else:
            kwargs["api_key"] = self.api_key
        return kwargs

    def call(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> str:
        litellm = _ensure_litellm()
        use_model = model or self.default_model
        last_err: Exception | None = None

        for attempt in range(max_retries):
            try:
                response = litellm.completion(
                    **self._completion_kwargs(
                        prompt=prompt,
                        model=use_model,
                        temperature=temperature,
                        stream=False,
                    )
                )
                text = _response_text(response)
                if not text.strip():
                    raise ValueError("API 返回空响应")
                return text
            except Exception as e:
                last_err = e
                logger.warning("LiteLLM 第 %s 次调用失败: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    break

        raise ValueError(f"LiteLLM 调用失败: {last_err}") from last_err

    def call_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        if not on_chunk:
            return self.call(prompt, model, temperature, max_retries)

        import time

        litellm = _ensure_litellm()
        use_model = model or self.default_model
        last_err: Exception | None = None

        for attempt in range(max_retries):
            full: list[str] = []
            try:
                stream = litellm.completion(
                    **self._completion_kwargs(
                        prompt=prompt,
                        model=use_model,
                        temperature=temperature,
                        stream=True,
                    )
                )
                for chunk in stream:
                    text = _chunk_text(chunk)
                    if text:
                        full.append(text)
                        on_chunk(text)
                result = "".join(full)
                if result.strip():
                    return result
                raise ValueError("流式响应为空")
            except Exception as e:
                last_err = e
                collected = "".join(full)
                logger.warning(
                    "LiteLLM 流式第 %s/%s 次异常: %s%s",
                    attempt + 1,
                    max_retries,
                    e,
                    f" (已收到 {len(collected)} 字符)" if collected else "",
                )
                if collected.strip() and attempt > 0:
                    return collected
                if attempt < max_retries - 1:
                    wait = min(2**attempt, 8)
                    time.sleep(wait)

        raise ValueError(
            f"LiteLLM 流式调用失败 (重试 {max_retries} 次): {last_err}"
        ) from last_err
