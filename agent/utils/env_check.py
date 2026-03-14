"""环境检查模块"""
from importlib.util import find_spec
from pathlib import Path
from typing import Tuple, List

from agent.utils.config import get_settings
from agent.utils.java_runtime import get_effective_java_home, is_bundled_java_path, is_project_java_path
from agent.utils.logger import get_logger
from agent.utils import secrets as secrets_utils

logger = get_logger(__name__)


class EnvCheckResult:
    """环境检查结果"""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
    
    def add_error(self, message: str):
        """添加错误"""
        self.errors.append(message)
    
    def add_warning(self, message: str):
        """添加警告"""
        self.warnings.append(message)
    
    def add_info(self, message: str):
        """添加信息"""
        self.info.append(message)
    
    def is_valid(self) -> bool:
        """检查是否有效（无错误）"""
        return len(self.errors) == 0
    
    def has_warnings(self) -> bool:
        """检查是否有警告"""
        return len(self.warnings) > 0


def check_environment() -> EnvCheckResult:
    """
    检查环境配置
    
    Returns:
        EnvCheckResult 对象
    """
    result = EnvCheckResult()
    settings = get_settings()
    
    # 1. 检查 LLM 后端配置
    backend = settings.llm_backend.lower()
    result.add_info(f"LLM 后端: {backend}")
    
    if backend == "deepseek":
        key = settings.get_api_key_for_backend("deepseek")
        if not key:
            result.add_error("DEEPSEEK_API_KEY 未配置，请设置环境变量、.env 或使用 keyring")
        else:
            result.add_info(f"DEEPSEEK_API_KEY 已配置（{secrets_utils.mask_key(key)}）")

    elif backend == "kimi":
        key = settings.get_api_key_for_backend("kimi")
        if not key:
            result.add_error("KIMI_API_KEY 未配置，请设置环境变量、.env 或使用 keyring")
        else:
            result.add_info(f"KIMI_API_KEY 已配置（{secrets_utils.mask_key(key)}）")

    elif backend == "openai-compatible":
        key = settings.get_api_key_for_backend("openai-compatible")
        if not key:
            result.add_error("OPENAI_COMPATIBLE_API_KEY 未配置，请设置环境变量、.env 或使用 keyring")
        else:
            result.add_info(f"OPENAI_COMPATIBLE_API_KEY 已配置（{secrets_utils.mask_key(key)}）")
        
        if not settings.openai_compatible_base_url:
            result.add_error("OPENAI_COMPATIBLE_BASE_URL 未配置（符合 OpenAI 规范的中转 API 需填写）")
        else:
            result.add_info(f"中转 API 基础 URL: {settings.openai_compatible_base_url}")
            # 测试连接
            try:
                import requests
                test_url = f"{settings.openai_compatible_base_url.rstrip('/')}/models"
                response = requests.get(test_url, timeout=5, headers={"Authorization": f"Bearer {settings.openai_compatible_api_key}"})
                if response.status_code == 200:
                    result.add_info("OpenAI 兼容 API 服务可访问")
                else:
                    result.add_warning(f"OpenAI 兼容 API 服务响应异常: {response.status_code}")
            except Exception as e:
                result.add_warning(f"无法连接到 OpenAI 兼容 API 服务: {e}")
                
    elif backend == "ollama":
        # 检查 Ollama 服务
        try:
            import requests
            test_url = f"{settings.ollama_url}/api/tags"
            response = requests.get(test_url, timeout=5)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                result.add_info(f"Ollama 服务可访问: {settings.ollama_url}")
                result.add_info(f"可用模型: {', '.join(model_names[:5])}" + (f" (共 {len(model_names)} 个)" if len(model_names) > 5 else ""))
            else:
                result.add_warning(f"Ollama 服务响应异常: {settings.ollama_url}")
        except Exception as e:
            result.add_error(f"无法连接到 Ollama 服务 ({settings.ollama_url}): {e}")
    else:
        result.add_error(f"不支持的 LLM 后端: {backend}，支持: deepseek, kimi, ollama, openai-compatible")
    
    # 2. 检查 COMSOL_JAR_PATH
    if not settings.comsol_jar_path:
        result.add_error("COMSOL_JAR_PATH 未配置，请设置环境变量或 .env 文件")
    else:
        jar_path = Path(settings.comsol_jar_path)
        if jar_path.exists():
            size_mb = jar_path.stat().st_size / (1024 * 1024)
            result.add_info(f"COMSOL JAR 文件存在: {jar_path} ({size_mb:.2f} MB)")
        else:
            result.add_error(f"COMSOL JAR 文件不存在: {jar_path}")
    
    # 3. 检查 Java（支持内置运行时：未配置 JAVA_HOME 时首次使用会自动下载 JDK 11）
    java_home = get_effective_java_home()
    if java_home:
        java_home_path = Path(java_home)
        if java_home_path.exists():
            java_exe = java_home_path / "bin" / "java.exe"
            if not java_exe.exists():
                java_exe = java_home_path / "bin" / "java"
            if java_exe.exists():
                if is_bundled_java_path(java_home):
                    suffix = "（项目内置 JDK 11）"
                elif is_project_java_path(java_home):
                    suffix = "（项目集成 Java）"
                else:
                    suffix = ""
                result.add_info(f"Java 可执行文件: {java_exe}{suffix}")
            else:
                result.add_warning(f"未找到 Java 可执行文件: {java_home_path / 'bin'}")
        else:
            result.add_error(f"JAVA_HOME 路径不存在: {java_home_path}")
    else:
        result.add_info("未配置 JAVA_HOME，首次使用 COMSOL 功能时将自动下载内置 JDK 11 到项目 runtime/java")
    
    # 4. 检查 MODEL_OUTPUT_DIR
    if not settings.model_output_dir:
        result.add_error("MODEL_OUTPUT_DIR 未配置")
    else:
        output_dir = Path(settings.model_output_dir)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            # 测试写入权限
            test_file = output_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            result.add_info(f"输出目录可访问: {output_dir}")
        except Exception as e:
            result.add_error(f"输出目录无法访问: {output_dir} ({e})")
    
    # 5. 检查 Python 依赖（deepseek/kimi/openai-compatible 均使用 openai 客户端）
    if backend in ["deepseek", "kimi", "openai-compatible"]:
        if find_spec("openai") is not None:
            result.add_info("openai 已安装")
        else:
            result.add_error("openai 未安装，请运行: pip install openai")
    
    try:
        import requests
        result.add_info("requests 已安装")
    except ImportError:
        result.add_error("requests 未安装，请运行: pip install requests")
    
    if find_spec("jpype") is not None:
        result.add_info("jpype1 已安装")
    else:
        result.add_error("jpype1 未安装，请运行: pip install jpype1")
    
    return result


def validate_environment() -> Tuple[bool, str]:
    """
    验证环境配置（简化版，用于启动前检查）
    
    Returns:
        (is_valid, error_message)
    """
    result = check_environment()
    
    if not result.is_valid():
        error_msg = "环境配置错误:\n" + "\n".join(f"  - {err}" for err in result.errors)
        return False, error_msg
    
    return True, ""


def print_check_result(result: EnvCheckResult):
    """打印检查结果（表格 + 面板）"""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    if result.is_valid():
        console.print(Panel("[bold green]✅ 环境检查通过[/bold green]", title="环境检查", border_style="green"))
    else:
        console.print(Panel("[bold red]❌ 环境检查失败[/bold red]", title="环境检查", border_style="red"))

    if result.errors:
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="red", width=4)
        t.add_column(style="white")
        for e in result.errors:
            t.add_row("❌", e)
        console.print(Panel(t, title="[red]错误[/red]", border_style="red"))
    if result.warnings:
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="yellow", width=4)
        t.add_column(style="white")
        for w in result.warnings:
            t.add_row("⚠", w)
        console.print(Panel(t, title="[yellow]警告[/yellow]", border_style="yellow"))
    if result.info:
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="cyan", width=4)
        t.add_column(style="white")
        for i in result.info:
            t.add_row("ℹ", i)
        console.print(Panel(t, title="[cyan]信息[/cyan]", border_style="cyan"))
