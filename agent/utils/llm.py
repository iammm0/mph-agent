"""LLM 工具函数 - 仅支持 DeepSeek、Kimi、Ollama 及符合 OpenAI 规范的中转 API"""

from abc import ABC, abstractmethod
from typing import Callable, Literal, Optional

from agent.utils.logger import get_logger

logger = get_logger(__name__)

_SUPPORTED_BACKENDS = ("deepseek", "kimi", "ollama", "openai-compatible")


class LLMBackend(ABC):
    """LLM 后端抽象基类"""

    @abstractmethod
    def call(self, prompt: str, model: str, temperature: float = 0.1, max_retries: int = 3) -> str:
        """调用 LLM API"""
        pass

    def call_stream(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.1,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """流式调用；若 on_chunk 为 None 或后端不支持流式，则退化为普通 call。返回完整响应文本。"""
        return self.call(prompt, model, temperature, max_retries)


def _openai_chat(
    client, prompt: str, model: str, temperature: float, max_retries: int, backend_name: str
) -> str:
    """通用 OpenAI 风格 chat 调用"""
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            response_text = response.choices[0].message.content
            if not response_text:
                raise ValueError("API 返回空响应")
            return response_text
        except Exception as e:
            logger.warning(f"{backend_name} 第 {attempt + 1} 次调用失败: {e}")
            if attempt == max_retries - 1:
                raise ValueError(f"{backend_name} API 调用失败: {e}") from e
    raise ValueError(f"{backend_name} API 调用失败，已达到最大重试次数")


def _openai_chat_stream(
    client,
    prompt: str,
    model: str,
    temperature: float,
    on_chunk: Callable[[str], None],
    backend_name: str,
    max_retries: int = 3,
) -> str:
    """OpenAI 风格流式 chat，每收到一段内容就调用 on_chunk；返回完整响应。含重试逻辑。"""
    import time

    last_err = None
    for attempt in range(max_retries):
        full: list[str] = []
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
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
                f"{backend_name} 流式第 {attempt + 1}/{max_retries} 次调用异常: {e}"
                + (f" (已收到 {len(collected)} 字符)" if collected else "")
            )
            if collected.strip() and attempt > 0:
                logger.info(f"{backend_name} 使用已收到的部分响应 ({len(collected)} 字符)")
                return collected
            if attempt < max_retries - 1:
                wait = min(2**attempt, 8)
                logger.info(f"{backend_name} {wait}s 后重试...")
                time.sleep(wait)

    raise ValueError(
        f"{backend_name} 流式调用失败 (重试 {max_retries} 次): {last_err}"
    ) from last_err


class DeepSeekBackend(LLMBackend):
    """DeepSeek 后端（OpenAI 兼容）"""

    def __init__(self, api_key: str):
        try:
            from openai import OpenAI  # type: ignore[import-not-found]

            self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        except ImportError:
            raise ImportError("openai 未安装，请运行: pip install openai")

    def call(
        self,
        prompt: str,
        model: str = "deepseek-reasoner",
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> str:
        return _openai_chat(self.client, prompt, model, temperature, max_retries, "DeepSeek")

    def call_stream(
        self,
        prompt: str,
        model: str = "deepseek-reasoner",
        temperature: float = 0.1,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        if not on_chunk:
            return self.call(prompt, model, temperature, max_retries)
        return _openai_chat_stream(
            self.client, prompt, model, temperature, on_chunk, "DeepSeek", max_retries=max_retries
        )


class KimiBackend(LLMBackend):
    """Kimi（Moonshot）后端（OpenAI 兼容）"""

    def __init__(self, api_key: str):
        try:
            from openai import OpenAI  # type: ignore[import-not-found]

            self.client = OpenAI(api_key=api_key, base_url="https://api.moonshot.ai/v1")
        except ImportError:
            raise ImportError("openai 未安装，请运行: pip install openai")

    def call(
        self,
        prompt: str,
        model: str = "moonshot-v1-8k",
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> str:
        return _openai_chat(self.client, prompt, model, temperature, max_retries, "Kimi")

    def call_stream(
        self,
        prompt: str,
        model: str = "moonshot-v1-8k",
        temperature: float = 0.1,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        if not on_chunk:
            return self.call(prompt, model, temperature, max_retries)
        return _openai_chat_stream(
            self.client, prompt, model, temperature, on_chunk, "Kimi", max_retries=max_retries
        )


class OpenAICompatibleBackend(LLMBackend):
    """符合 OpenAI 规范的中转 API 后端"""

    def __init__(self, api_key: str, base_url: str):
        try:
            from openai import OpenAI  # type: ignore[import-not-found]

            self.client = OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:
            raise ImportError("openai 未安装，请运行: pip install openai")
        self.base_url = base_url
        logger.info(f"使用 OpenAI 兼容中转 API: {base_url}")

    def call(
        self,
        prompt: str,
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> str:
        return _openai_chat(self.client, prompt, model, temperature, max_retries, "OpenAI兼容")

    def call_stream(
        self,
        prompt: str,
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.1,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        if not on_chunk:
            return self.call(prompt, model, temperature, max_retries)
        return _openai_chat_stream(
            self.client, prompt, model, temperature, on_chunk, "OpenAI兼容", max_retries=max_retries
        )


class OllamaBackend(LLMBackend):
    """Ollama 后端（支持本地和远程）"""

    def __init__(self, base_url: str = "http://localhost:11434"):
        """
        初始化 Ollama 后端

        Args:
            base_url: Ollama 服务地址，默认本地 http://localhost:11434
        """
        self.base_url = base_url.rstrip("/")
        try:
            import requests  # type: ignore[import-not-found]

            self.requests = requests
        except ImportError:
            raise ImportError("requests 未安装，请运行: pip install requests")

    def call(
        self, prompt: str, model: str = "llama3", temperature: float = 0.1, max_retries: int = 3
    ) -> str:
        """调用 Ollama API"""
        api_url = f"{self.base_url}/api/generate"

        for attempt in range(max_retries):
            try:
                logger.debug(f"调用 Ollama API (尝试 {attempt + 1}/{max_retries})")
                logger.debug(f"Ollama 服务地址: {self.base_url}, 模型: {model}")

                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                    },
                }

                response = self.requests.post(api_url, json=payload, timeout=120)
                response.raise_for_status()

                result = response.json()
                response_text = result.get("response", "")

                if not response_text:
                    raise ValueError("Ollama API 返回空响应")

                logger.debug(f"Ollama 响应长度: {len(response_text)} 字符")

                return response_text

            except self.requests.exceptions.ConnectionError as e:
                error_msg = f"无法连接到 Ollama 服务 ({self.base_url})，请确保 Ollama 正在运行"
                logger.warning(f"第 {attempt + 1} 次调用失败: {error_msg}")
                if attempt == max_retries - 1:
                    raise ValueError(error_msg) from e
            except Exception as e:
                logger.warning(f"第 {attempt + 1} 次调用失败: {e}")
                if attempt == max_retries - 1:
                    raise ValueError(f"Ollama API 调用失败: {e}") from e

        raise ValueError("Ollama API 调用失败，已达到最大重试次数")

    def call_stream(
        self,
        prompt: str,
        model: str = "llama3",
        temperature: float = 0.1,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        if not on_chunk:
            return self.call(prompt, model, temperature, max_retries)
        api_url = f"{self.base_url}/api/generate"
        full = []
        for attempt in range(max_retries):
            try:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": temperature},
                }
                resp = self.requests.post(api_url, json=payload, timeout=120, stream=True)
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        obj = __import__("json").loads(line)
                        piece = obj.get("response", "")
                        if piece:
                            full.append(piece)
                            on_chunk(piece)
                        if obj.get("done"):
                            break
                    except Exception:
                        pass
                return "".join(full)
            except Exception as e:
                logger.warning("Ollama 流式第 %s 次失败: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    raise ValueError(f"Ollama 流式调用失败: {e}") from e
        return "".join(full)

    def list_models(self) -> list:
        """列出可用的模型"""
        try:
            api_url = f"{self.base_url}/api/tags"
            response = self.requests.get(api_url, timeout=10)
            response.raise_for_status()
            result = response.json()
            return [model["name"] for model in result.get("models", [])]
        except Exception as e:
            logger.warning(f"获取模型列表失败: {e}")
            return []


class LLMClient:
    """LLM 客户端封装 - 仅支持 DeepSeek、Kimi、Ollama、OpenAI 兼容中转"""

    def __init__(
        self,
        backend: Literal["deepseek", "kimi", "ollama", "openai-compatible"] = "ollama",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """
        初始化 LLM 客户端

        支持的后端: deepseek, kimi, ollama, openai-compatible（符合 OpenAI 规范的中转 API）
        """
        self.backend_type = backend
        self.model = model

        if backend == "deepseek":
            if not api_key:
                raise ValueError("使用 deepseek 后端需要提供 api_key")
            self.backend = DeepSeekBackend(api_key)
            self.default_model = model or "deepseek-reasoner"

        elif backend == "kimi":
            if not api_key:
                raise ValueError("使用 kimi 后端需要提供 api_key")
            self.backend = KimiBackend(api_key)
            self.default_model = model or "moonshot-v1-8k"

        elif backend == "openai-compatible":
            if not api_key:
                raise ValueError("使用 openai-compatible 后端需要提供 api_key")
            if not base_url:
                raise ValueError("使用 openai-compatible 后端需要提供 base_url")
            self.backend = OpenAICompatibleBackend(api_key, base_url)
            self.default_model = model or "gpt-3.5-turbo"

        elif backend == "ollama":
            ollama_url = ollama_url or "http://localhost:11434"
            self.backend = OllamaBackend(ollama_url)
            self.default_model = model or "llama3"

        else:
            raise ValueError(f"不支持的后端: {backend}，支持: {', '.join(_SUPPORTED_BACKENDS)}")

        logger.info(f"LLM 客户端已初始化: {backend}, 模型: {self.default_model}")

    def call(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> str:
        """
        调用 LLM API

        Args:
            prompt: 输入提示
            model: 模型名称（可选，使用初始化时的默认值）
            temperature: 温度参数
            max_retries: 最大重试次数

        Returns:
            LLM 响应文本

        Raises:
            ValueError: API 调用失败
        """
        model = model or self.default_model
        return self.backend.call(prompt, model, temperature, max_retries)

    def call_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """流式调用；on_chunk 每收到一段内容调用一次。返回完整响应。"""
        model = model or self.default_model
        return self.backend.call_stream(prompt, model, temperature, max_retries, on_chunk=on_chunk)
