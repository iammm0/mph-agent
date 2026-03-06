#!/usr/bin/env python3
"""
最小示例：用 Python 调 COMSOL Java API，生成一个只含一个矩形的 .mph 文件。

依赖：.env 中已配置 COMSOL_JAR_PATH（及可选 JAVA_HOME、COMSOL_NATIVE_PATH）。
运行：在项目根目录执行
  uv run python scripts/py_to_mph_minimal.py
输出：在 mph-agent 根目录下的 models/ 中生成 minimal_model.mph。
"""
import os
from pathlib import Path
import sys

# 保证项目根在 path 并加载 .env
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

from agent.utils.java_runtime import ensure_java_home_from_venv
ensure_java_home_from_venv(_project_root)

from schemas.geometry import GeometryPlan, GeometryShape
from agent.executor.comsol_runner import COMSOLRunner
from agent.utils.config import get_settings


def main() -> None:
    print("1. 检查配置...")
    settings = get_settings()
    java_home = os.environ.get("JAVA_HOME", "")
    print(f"   JAVA_HOME: {java_home or '(未设置)'}")
    print(f"   COMSOL_JAR_PATH: {settings.comsol_jar_path}")
    if not settings.comsol_jar_path or not Path(settings.comsol_jar_path).exists():
        print("错误: 请设置 .env 中的 COMSOL_JAR_PATH 并指向有效路径。")
        sys.exit(1)
    out_dir = Path(settings.model_output_dir or _project_root / "models")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = "minimal_model.mph"

    print("2. 构建最小几何计划（一个 1m×0.5m 矩形）...")
    plan = GeometryPlan(
        model_name="minimal_model",
        units="m",
        shapes=[
            GeometryShape(
                type="rectangle",
                parameters={"width": 1.0, "height": 0.5},
                position={"x": 0.0, "y": 0.0},
                name="rect1",
            )
        ],
    )

    print("3. 启动 JVM 并调用 COMSOL Java API 创建、保存模型...")
    runner = COMSOLRunner()
    out_path = runner.create_model_from_plan(plan, output_filename=out_file)

    print(f"4. 完成。输出: {out_path}")
    assert out_path.exists(), "输出文件未生成"
    print(f"   文件大小: {out_path.stat().st_size} 字节")


if __name__ == "__main__":
    main()
