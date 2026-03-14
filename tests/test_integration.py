"""端到端集成测试（使用 agent 包与 schemas）。"""
from schemas.geometry import GeometryPlan, GeometryShape


class TestIntegration:
    """集成测试"""

    def test_geometry_plan_to_dict(self):
        """测试 GeometryPlan 序列化"""
        shapes = [
            GeometryShape(
                type="rectangle",
                parameters={"width": 1.0, "height": 0.5},
                position={"x": 0.0, "y": 0.0},
            )
        ]
        plan = GeometryPlan(shapes=shapes, model_name="test")
        plan_dict = plan.to_dict()
        assert "model_name" in plan_dict
        assert "units" in plan_dict
        assert "shapes" in plan_dict
        assert len(plan_dict["shapes"]) == 1

    def test_geometry_plan_from_dict(self):
        """测试 GeometryPlan 反序列化"""
        plan_dict = {
            "model_name": "test",
            "units": "m",
            "shapes": [
                {
                    "type": "rectangle",
                    "parameters": {"width": 1.0, "height": 0.5},
                    "position": {"x": 0.0, "y": 0.0},
                    "name": "rect1",
                }
            ],
        }
        plan = GeometryPlan.from_dict(plan_dict)
        assert plan.model_name == "test"
        assert len(plan.shapes) == 1
        assert plan.shapes[0].type == "rectangle"
