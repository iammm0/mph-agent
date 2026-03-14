"""Executor 单元测试：JavaGenerator 代码生成（不启动 JVM）。"""
import pytest
from unittest.mock import patch, Mock

from schemas.geometry import GeometryPlan, GeometryShape
from agent.executor.java_generator import JavaGenerator


@pytest.fixture
def mock_settings():
    with patch("agent.executor.java_generator.get_settings") as m:
        m.return_value.model_output_dir = "/tmp/models"
        yield m


@pytest.fixture
def sample_plan():
    return GeometryPlan(
        model_name="test_model",
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


@pytest.fixture
def plan_with_circle():
    return GeometryPlan(
        model_name="circle_model",
        units="m",
        shapes=[
            GeometryShape(
                type="circle",
                parameters={"radius": 0.3},
                position={"x": 0.0, "y": 0.0},
                name="circ1",
            )
        ],
    )


@pytest.fixture
def plan_with_ellipse():
    return GeometryPlan(
        model_name="ellipse_model",
        units="m",
        shapes=[
            GeometryShape(
                type="ellipse",
                parameters={"a": 1.0, "b": 0.6},
                position={"x": 0.5, "y": 0.5},
                name="ell1",
            )
        ],
    )


class TestJavaGenerator:
    """JavaGenerator：generate_from_plan、_generate_direct_code、_generate_shape_code"""

    def test_generate_from_plan_uses_direct_code_when_template_empty(self, mock_settings, sample_plan):
        with patch("agent.executor.java_generator.prompt_loader") as mock_loader:
            mock_loader.format.return_value = ""  # 模拟模板返回空，走 _generate_direct_code
            gen = JavaGenerator()
            code = gen.generate_from_plan(sample_plan, output_filename="out.mph")
            assert "import com.comsol" in code
            assert "geom1" in code
            assert "rect1" in code or "Rectangle" in code
            assert "model.save" in code or "save" in code

    def test_generate_shape_code_rectangle(self, mock_settings):
        gen = JavaGenerator()
        shape = GeometryShape(
            type="rectangle",
            parameters={"width": 2.0, "height": 1.0},
            position={"x": 1.0, "y": 0.5},
            name="r1",
        )
        code = gen._generate_shape_code(shape, 1)
        assert "2.0" in code
        assert "1.0" in code
        assert "1.0" in code and "0.5" in code  # pos

    def test_generate_shape_code_circle(self, mock_settings):
        gen = JavaGenerator()
        shape = GeometryShape(
            type="circle",
            parameters={"radius": 0.3},
            position={"x": 0.0, "y": 0.0},
            name="c1",
        )
        code = gen._generate_shape_code(shape, 1)
        assert "0.3" in code
        assert "Circle" in code or "circle" in code

    def test_generate_shape_code_ellipse(self, mock_settings):
        gen = JavaGenerator()
        shape = GeometryShape(
            type="ellipse",
            parameters={"a": 1.0, "b": 0.6},
            position={"x": 0.0, "y": 0.0},
            name="e1",
        )
        code = gen._generate_shape_code(shape, 1)
        assert "1.0" in code
        assert "0.6" in code
        assert "Ellipse" in code or "ellipse" in code

    def test_generate_shape_code_unsupported_type_raises(self, mock_settings):
        gen = JavaGenerator()
        shape = Mock()
        shape.type = "unknown"
        shape.parameters = {}
        shape.position = {"x": 0, "y": 0}
        shape.name = "x1"
        with pytest.raises(ValueError, match="不支持的形状类型"):
            gen._generate_shape_code(shape, 1)
