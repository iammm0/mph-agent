"""PyInstaller 打包用入口：仅运行 tui-bridge，供桌面安装包内嵌。勿直接运行。"""
import os
import sys
from pathlib import Path

# 在任何可能 import litellm 的代码之前：避免启动时访问 raw.githubusercontent.com
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

if getattr(sys, "frozen", False):
    _root = Path(sys.executable).resolve().parent
else:
    _root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

if __name__ == "__main__":
    from dotenv import load_dotenv
    from agent.utils.java_runtime import ensure_java_home_from_venv

    load_dotenv(_root / ".env")
    ensure_java_home_from_venv(_root)
    from agent.run.tui_bridge import main
    main()
