"""开发测试脚本"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.planner.geometry_agent import GeometryAgent
from agent.utils.logger import setup_logging, get_logger
from schemas.geometry import GeometryPlan

logger = get_logger(__name__)


def test_planner():
    """测试 Planner Agent"""
    print("=" * 60)
    print("测试 Planner Agent")
    print("=" * 60)
    
    setup_logging("DEBUG")
    
    try:
        agent = GeometryAgent()
        
        test_cases = [
            "创建一个宽1米、高0.5米的矩形",
            "在原点放置一个半径为0.3米的圆",
            "创建一个长轴1米、短轴0.6米的椭圆，中心在(0.5, 0.5)",
        ]
        
        for i, test_input in enumerate(test_cases, 1):
            print(f"\n测试用例 {i}: {test_input}")
            try:
                plan = agent.parse(test_input)
                print(f"✅ 解析成功: {len(plan.shapes)} 个形状")
                print(f"   模型名称: {plan.model_name}")
                print(f"   单位: {plan.units}")
                for j, shape in enumerate(plan.shapes, 1):
                    print(f"   形状 {j}: {shape.type}, 参数: {shape.parameters}")
            except Exception as e:
                print(f"❌ 解析失败: {e}")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False
    
    return True


def test_schema():
    """测试 Schema"""
    print("\n" + "=" * 60)
    print("测试 Schema")
    print("=" * 60)
    
    try:
        from schemas.geometry import GeometryShape, GeometryPlan
        
        # 测试矩形
        rect = GeometryShape(
            type="rectangle",
            parameters={"width": 1.0, "height": 0.5},
            position={"x": 0.0, "y": 0.0}
        )
        print(f"✅ 矩形创建成功: {rect.type}")
        
        # 测试圆形
        circle = GeometryShape(
            type="circle",
            parameters={"radius": 0.3},
            position={"x": 0.0, "y": 0.0}
        )
        print(f"✅ 圆形创建成功: {circle.type}")
        
        # 测试计划
        plan = GeometryPlan(shapes=[rect, circle], model_name="test_model")
        print(f"✅ 计划创建成功: {plan.model_name}, {len(plan.shapes)} 个形状")
        
        # 测试序列化
        plan_dict = plan.to_dict()
        print(f"✅ 序列化成功: {len(plan_dict['shapes'])} 个形状")
        
        # 测试反序列化
        plan2 = GeometryPlan.from_dict(plan_dict)
        print(f"✅ 反序列化成功: {plan2.model_name}")
        
    except Exception as e:
        print(f"❌ Schema 测试失败: {e}")
        return False
    
    return True


if __name__ == "__main__":
    print("mph-agent 开发测试")
    print("=" * 60)
    
    success = True
    success &= test_schema()
    success &= test_planner()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ 所有测试通过")
    else:
        print("❌ 部分测试失败")
    print("=" * 60)
    
    sys.exit(0 if success else 1)
