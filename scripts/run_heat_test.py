"""临时脚本：测试传热稳态建模命令（等价于 cli run -o heat_steady.mph）"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

def main():
    from dotenv import load_dotenv
    from agent.utils.java_runtime import ensure_java_home_from_venv
    from agent.core.dependencies import get_agent, get_context_manager
    from agent.utils.env_check import validate_environment
    from agent.utils.logger import setup_logging, get_logger

    load_dotenv(root / ".env")
    ensure_java_home_from_venv(root)

    setup_logging("DEBUG")
    logger = get_logger(__name__)
    is_valid, err = validate_environment()
    if not is_valid:
        print("环境检查失败:", err)
        return 1
    input_text = "创建一个传热模型，包含一个矩形域，设置温度边界条件，进行稳态求解"
    output_name = "heat_steady.mph"
    logger.info("输入: %s", input_text)
    logger.info("输出: %s", output_name)
    core = get_agent("core")
    model_path = core.run(input_text, output_name)
    print("模型已生成:", model_path)
    ctx = get_context_manager()
    ctx.add_conversation(user_input=input_text, plan={"architecture": "react"}, model_path=str(model_path), success=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
