"""主启动程序 - 用于调试和开发。推荐使用 uv run python cli.py 启动桌面应用。"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    from cli import main

    main()
