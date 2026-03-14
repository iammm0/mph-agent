"""配置管理"""
import sys
from pathlib import Path
from typing import Optional, Dict

from pydantic_settings import BaseSettings
from dotenv import load_dotenv

from agent.utils import secrets as secrets_utils

# 加载 .env 文件
load_dotenv()


def get_install_dir() -> Path:
    """获取安装目录（包或可执行文件所在目录）"""
    # 尝试从包元数据获取
    try:
        import importlib.metadata
        dist = importlib.metadata.distribution("mph-agent")
        if dist and dist.locate_file:
            return Path(dist.locate_file("")).parent
    except Exception:
        pass

    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


def get_project_root() -> Path:
    """
    获取当前项目根目录（含 pyproject.toml 的目录），用于保存到「项目下的 models」而非虚拟环境内。
    从本文件所在路径或 cwd 向上查找 pyproject.toml。
    """
    # 从 config 所在路径向上找
    start = Path(__file__).resolve().parent
    for parent in [start, *start.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    # 从当前工作目录向上找
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return get_install_dir()


def get_default_output_dir() -> str:
    """获取默认输出目录（mph-agent 根目录下的 models，唯一且首要；项目根上一级 models 不再使用）"""
    return str(get_project_root() / "models")


class Settings(BaseSettings):
    """应用配置"""
    
    # LLM 后端配置（仅支持: deepseek, kimi, ollama, openai-compatible）
    llm_backend: str = "ollama"

    # DeepSeek API 配置（默认使用 reasoner，可选 deepseek-chat）
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-reasoner"

    # Kimi (Moonshot) API 配置
    kimi_api_key: str = ""
    kimi_model: str = "moonshot-v1-8k"

    # 符合 OpenAI 规范的中转 API 配置
    openai_compatible_api_key: str = ""
    openai_compatible_base_url: str = ""
    openai_compatible_model: str = "gpt-3.5-turbo"

    # Ollama 配置
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    
    # COMSOL 配置
    comsol_jar_path: str = ""
    # COMSOL 本地库目录（含 JNI .dll/.so），用于 -Djava.library.path，解决 UnsatisfiedLinkError: FlLicense.initWS0
    comsol_native_path: str = ""
    java_home: Optional[str] = None
    model_output_dir: str = ""
    # 内置 JDK 下载镜像：留空用官方 Adoptium；设为 tsinghua 使用清华镜像（国内加速）
    java_download_mirror: str = ""
    # 为 true 时禁用自动下载 JDK，仅使用已存在的 JAVA_HOME 或 runtime/java（环境已就绪时可用）
    java_skip_auto_download: bool = False
    
    # 日志配置
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 如果未设置输出目录，使用默认值
        if not self.model_output_dir:
            self.model_output_dir = get_default_output_dir()

    def get_api_key_for_backend(self, backend: str) -> Optional[str]:
        """获取当前后端的 API Key。顺序：环境变量优先，再 keyring。"""
        if backend == "ollama":
            return None
        key = secrets_utils.get_api_key(backend)
        if key:
            return key
        if backend == "deepseek":
            return self.deepseek_api_key or None
        if backend == "kimi":
            return self.kimi_api_key or None
        if backend == "openai-compatible":
            return self.openai_compatible_api_key or None
        return None

    def get_base_url_for_backend(self, backend: str) -> Optional[str]:
        """获取当前后端的 API base URL（仅 openai-compatible 需要）。"""
        if backend == "openai-compatible":
            return self.openai_compatible_base_url or None
        return None

    def get_model_for_backend(self, backend: str) -> str:
        """获取当前后端的模型名称。"""
        if backend == "deepseek":
            return self.deepseek_model or "deepseek-reasoner"
        if backend == "kimi":
            return self.kimi_model or "moonshot-v1-8k"
        if backend == "openai-compatible":
            return self.openai_compatible_model or "gpt-3.5-turbo"
        if backend == "ollama":
            return self.ollama_model or "llama3"
        return ""

    def show_config_status(self) -> Dict[str, bool]:
        """返回各 provider 是否已配置（不暴露密钥）。"""
        status: Dict[str, bool] = {}
        for provider in ("deepseek", "kimi", "openai-compatible"):
            status[provider] = bool(self.get_api_key_for_backend(provider))
        status["ollama"] = bool(self.ollama_url and self.ollama_url.strip())
        return status


# 全局配置实例
_settings: Optional[Settings] = None


def reload_settings() -> None:
    """清空单例，下次 get_settings() 时重新从 .env 加载。"""
    global _settings
    _settings = None


def get_settings() -> Settings:
    """获取配置实例（单例）"""
    global _settings
    if _settings is None:
        _settings = Settings()
        # 确保输出目录存在
        Path(_settings.model_output_dir).mkdir(parents=True, exist_ok=True)
    return _settings
