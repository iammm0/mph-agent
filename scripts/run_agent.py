"""运行 Agent 的主脚本"""
import sys
import argparse
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def main():
    """主函数"""
    from agent.planner.geometry_agent import GeometryAgent
    from agent.executor.comsol_runner import COMSOLRunner
    from agent.utils.logger import setup_logging, get_logger

    parser = argparse.ArgumentParser(
        description="COMSOL Multiphysics Agent - 将自然语言转换为 COMSOL 模型文件"
    )
    parser.add_argument(
        "input",
        type=str,
        help="自然语言描述的几何建模需求"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="输出文件名（不含路径）"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志"
    )
    
    args = parser.parse_args()
    
    # 配置日志
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(log_level)
    logger = get_logger(__name__)
    
    try:
        logger.info("=" * 60)
        logger.info("开始创建 COMSOL 模型")
        logger.info("=" * 60)
        
        # 步骤 1: Planner Agent 解析自然语言
        logger.info("步骤 1: 解析自然语言...")
        planner = GeometryAgent()
        plan = planner.parse(args.input)
        logger.info(f"解析成功: {len(plan.shapes)} 个形状")
        
        # 步骤 2: 创建 COMSOL 模型
        logger.info("步骤 2: 创建 COMSOL 模型...")
        runner = COMSOLRunner()
        model_path = runner.create_model_from_plan(plan, args.output)
        
        logger.info("=" * 60)
        logger.info(f"✅ 模型创建成功: {model_path}")
        logger.info("=" * 60)
        
        print(f"\n✅ 模型已生成: {model_path}")
        return 0
        
    except Exception as e:
        logger.error(f"❌ 创建模型失败: {e}")
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
