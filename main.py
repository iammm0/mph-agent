"""主启动程序 - 用于调试和开发。推荐使用 uv run mph-agent（无参数）进入全终端 TUI。"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 委托给 cli 入口
from cli import main

if __name__ == "__main__":
    main()
