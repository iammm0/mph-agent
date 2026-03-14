"""Java 代码生成器 — 支持 2D/3D 几何、材料"""
import json
from pathlib import Path
from typing import Optional

from agent.utils.prompt_loader import prompt_loader
from agent.utils.logger import get_logger
from agent.utils.config import get_settings
from schemas.geometry import GeometryPlan, GeometryShape

logger = get_logger(__name__)


class JavaGenerator:
    """Java 代码生成器"""

    def __init__(self):
        self.settings = get_settings()

    def generate_from_plan(self, plan: GeometryPlan, output_filename: Optional[str] = None) -> str:
        logger.info(f"生成 Java 代码，模型: {plan.model_name}, 维度: {plan.dimension}D")

        if output_filename is None:
            output_filename = f"{plan.model_name}.mph"

        output_path = str(Path(self.settings.model_output_dir) / output_filename)
        plan_json = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)

        java_code = prompt_loader.format("executor", "java_codegen", plan_json=plan_json)

        if not java_code or "import" not in java_code:
            java_code = self._generate_direct_code(plan, output_path)

        logger.debug(f"生成的 Java 代码长度: {len(java_code)} 字符")
        return java_code

    def _generate_direct_code(self, plan: GeometryPlan, output_path: str) -> str:
        dim = plan.dimension

        imports = (
            "import com.comsol.model.*;\n"
            "import com.comsol.model.util.*;\n\n"
        )

        main_start = (
            f"public class COMSOLModelGenerator {{\n"
            f"    public static void main(String[] args) {{\n"
            f"        try {{\n"
            f"            Model model = ModelUtil.create(\"{plan.model_name}\");\n"
            f"            model.component().create(\"comp1\");\n"
            f"            model.component(\"comp1\").geom().create(\"geom1\", {dim});\n\n"
        )

        shapes_code = ""
        for i, shape in enumerate(plan.shapes, 1):
            shapes_code += self._generate_shape_code(shape, i, dim)

        operations_code = ""
        for op in plan.operations:
            operations_code += self._generate_operation_code_snippet(op)

        build_geom = (
            "\n            model.component(\"comp1\").geom(\"geom1\").run();\n\n"
        )

        save_model = (
            f"            model.save(\"{output_path}\");\n"
            f"            System.out.println(\"模型已保存到: {output_path}\");\n\n"
            f"        }} catch (Exception e) {{\n"
            f"            System.err.println(\"错误: \" + e.getMessage());\n"
            f"            e.printStackTrace();\n"
            f"            System.exit(1);\n"
            f"        }}\n"
            f"    }}\n"
            f"}}\n"
        )

        return imports + main_start + shapes_code + operations_code + build_geom + save_model

    def _generate_shape_code(self, shape: GeometryShape, index: int, dim: int = 2) -> str:
        name = shape.name or f"{shape.type}{index}"
        x = shape.position.get("x", 0.0)
        y = shape.position.get("y", 0.0)
        z = shape.position.get("z", 0.0)
        geom = 'model.component("comp1").geom("geom1")'

        if shape.type == "rectangle":
            w, h = shape.parameters["width"], shape.parameters["height"]
            return (
                f'            {geom}.create("{name}", "Rectangle");\n'
                f'            {geom}.feature("{name}").set("size", new double[]{{{w}, {h}}});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}}});\n\n'
            )

        if shape.type == "circle":
            r = shape.parameters["radius"]
            return (
                f'            {geom}.create("{name}", "Circle");\n'
                f'            {geom}.feature("{name}").set("r", {r});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}}});\n\n'
            )

        if shape.type == "ellipse":
            a, b = shape.parameters["a"], shape.parameters["b"]
            return (
                f'            {geom}.create("{name}", "Ellipse");\n'
                f'            {geom}.feature("{name}").set("a", {a});\n'
                f'            {geom}.feature("{name}").set("b", {b});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}}});\n\n'
            )

        if shape.type == "block":
            w = shape.parameters["width"]
            h = shape.parameters["height"]
            d = shape.parameters["depth"]
            return (
                f'            {geom}.create("{name}", "Block");\n'
                f'            {geom}.feature("{name}").set("size", new double[]{{{w}, {d}, {h}}});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}, {z}}});\n\n'
            )

        if shape.type == "cylinder":
            r, h = shape.parameters["radius"], shape.parameters["height"]
            return (
                f'            {geom}.create("{name}", "Cylinder");\n'
                f'            {geom}.feature("{name}").set("r", {r});\n'
                f'            {geom}.feature("{name}").set("h", {h});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}, {z}}});\n\n'
            )

        if shape.type == "sphere":
            r = shape.parameters["radius"]
            return (
                f'            {geom}.create("{name}", "Sphere");\n'
                f'            {geom}.feature("{name}").set("r", {r});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}, {z}}});\n\n'
            )

        if shape.type == "cone":
            rb = shape.parameters["radius_bottom"]
            rt = shape.parameters.get("radius_top", 0.0)
            h = shape.parameters["height"]
            return (
                f'            {geom}.create("{name}", "Cone");\n'
                f'            {geom}.feature("{name}").set("r", {rb});\n'
                f'            {geom}.feature("{name}").set("rtop", {rt});\n'
                f'            {geom}.feature("{name}").set("h", {h});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}, {z}}});\n\n'
            )

        if shape.type == "torus":
            rmaj = shape.parameters["radius_major"]
            rmin = shape.parameters["radius_minor"]
            return (
                f'            {geom}.create("{name}", "Torus");\n'
                f'            {geom}.feature("{name}").set("rmaj", {rmaj});\n'
                f'            {geom}.feature("{name}").set("rmin", {rmin});\n'
                f'            {geom}.feature("{name}").set("pos", new double[]{{{x}, {y}, {z}}});\n\n'
            )

        if shape.type == "polygon":
            xs = shape.parameters["x"]
            ys = shape.parameters["y"]
            xs_str = ", ".join(str(v) for v in xs)
            ys_str = ", ".join(str(v) for v in ys)
            return (
                f'            {geom}.create("{name}", "Polygon");\n'
                f'            {geom}.feature("{name}").set("x", new double[]{{{xs_str}}});\n'
                f'            {geom}.feature("{name}").set("y", new double[]{{{ys_str}}});\n\n'
            )

        raise ValueError(f"不支持的形状类型: {shape.type}")

    def _generate_operation_code_snippet(self, op) -> str:
        geom = 'model.component("comp1").geom("geom1")'
        inputs_str = ", ".join(f'"{n}"' for n in op.input)
        input_arr = f"new String[]{{{inputs_str}}}"
        keep = "true" if op.keep_input else "false"

        if op.type in ("union", "difference", "intersection"):
            tag = {"union": "Union", "difference": "Difference", "intersection": "Intersection"}[op.type]
            return (
                f'            {geom}.create("{op.name}", "{tag}");\n'
                f'            {geom}.feature("{op.name}").set("input", {input_arr});\n'
                f'            {geom}.feature("{op.name}").set("keep", {keep});\n\n'
            )

        if op.type == "extrude":
            dist = op.parameters.get("distance", 1.0)
            return (
                f'            {geom}.create("{op.name}", "Extrude");\n'
                f'            {geom}.feature("{op.name}").set("input", {input_arr});\n'
                f'            {geom}.feature("{op.name}").set("distance", {dist});\n\n'
            )

        if op.type == "revolve":
            angle = op.parameters.get("angle", 360.0)
            return (
                f'            {geom}.create("{op.name}", "Revolve");\n'
                f'            {geom}.feature("{op.name}").set("input", {input_arr});\n'
                f'            {geom}.feature("{op.name}").set("angle1", {angle});\n\n'
            )

        return f'            // TODO: 操作 {op.type} 暂未支持代码生成\n\n'
