"""COMSOL API 运行器 — 支持 2D/3D 几何"""
import os
import platform
import shutil
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from agent.utils.config import get_settings, get_project_root
from agent.utils.java_runtime import ensure_bundled_java
from agent.utils.logger import get_logger
from schemas.geometry import GeometryPlan, GeometryShape

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def _jpype():
    """延迟导入 jpype，便于 bridge 在未安装 jpype1 时也能启动；缺包时在首次使用 COMSOL 时报错。"""
    try:
        import jpype
        return jpype
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "未找到 jpype 模块，COMSOL 功能需要安装 jpype1。请在项目根目录执行: uv sync 或 pip install jpype1"
        ) from e


def _resolve_comsol_native_path(settings) -> Optional[str]:
    if getattr(settings, "comsol_native_path", None) and Path(settings.comsol_native_path).exists():
        return str(Path(settings.comsol_native_path).resolve())
    jar_path = Path(settings.comsol_jar_path)
    if not jar_path.exists():
        return None
    if jar_path.is_dir():
        base = jar_path.parent
    else:
        base = jar_path.parent.parent
    sep = ";" if os.name == "nt" else ":"
    if platform.system() == "Windows":
        lib_dir = base / "lib" / "win64"
        bin_dir = base / "bin" / "win64"
        license_dir = base / "license" / "win64"
        license_lmadmin = base / "license" / "win64" / "lmadmin"
    elif platform.system() == "Darwin":
        lib_dir = base / "lib" / "darwin64"
        bin_dir = base / "bin" / "darwin64"
        license_dir = license_lmadmin = None
    else:
        lib_dir = base / "lib" / "glnxa64"
        bin_dir = base / "bin" / "glnxa64"
        license_dir = license_lmadmin = None
    parts = []
    if lib_dir.exists():
        parts.append(str(lib_dir.resolve()))
    if bin_dir.exists() and str(bin_dir.resolve()) not in parts:
        parts.append(str(bin_dir.resolve()))
    if license_dir and license_dir.exists() and str(license_dir.resolve()) not in parts:
        parts.append(str(license_dir.resolve()))
    if license_lmadmin and license_lmadmin.exists() and str(license_lmadmin.resolve()) not in parts:
        parts.append(str(license_lmadmin.resolve()))
    if not parts:
        return None
    return sep.join(parts)


def _get_comsol_jvm_path(settings) -> Optional[str]:
    jar_path = Path(settings.comsol_jar_path)
    if not jar_path.exists():
        return None
    base = jar_path.parent if jar_path.is_dir() else jar_path.parent.parent
    if platform.system() == "Windows":
        jvm_dll = base / "java" / "win64" / "jre" / "bin" / "server" / "jvm.dll"
    elif platform.system() == "Darwin":
        jvm_dll = base / "java" / "darwin64" / "jre" / "lib" / "server" / "libjvm.dylib"
    else:
        jvm_dll = base / "java" / "glnxa64" / "jre" / "lib" / "amd64" / "server" / "libjvm.so"
    if jvm_dll.exists():
        return str(jvm_dll.resolve())
    return None


def _build_classpath(jar_path: str) -> str:
    path = Path(jar_path)
    if not path.exists():
        raise RuntimeError(f"COMSOL JAR 路径不存在: {jar_path}")
    sep = ";" if os.name == "nt" else ":"
    if path.is_dir():
        jars = sorted(path.glob("*.jar"))
        if not jars:
            raise RuntimeError(f"目录中未找到任何 .jar 文件: {jar_path}")
        return sep.join(str(p) for p in jars)
    return str(path)


class COMSOLRunner:
    """COMSOL Java API 运行器"""

    _jvm_started = False

    def __init__(self):
        self._ensure_jvm_started()
        self.settings = get_settings()

    @classmethod
    def _ensure_jvm_started(cls):
        if cls._jvm_started:
            return

        logger.info("启动 JVM...")
        settings = get_settings()
        if not settings.comsol_jar_path:
            raise RuntimeError("COMSOL JAR 路径未配置，请设置 COMSOL_JAR_PATH")

        classpath = _build_classpath(settings.comsol_jar_path)
        comsol_jvm = _get_comsol_jvm_path(settings)
        if comsol_jvm:
            java_home = str(Path(comsol_jvm).resolve().parent.parent.parent)
            logger.info("使用 COMSOL 自带 JRE: %s", java_home)
        else:
            java_home = ensure_bundled_java()
        os.environ["JAVA_HOME"] = java_home
        jvm_args = [f"-Djava.class.path={classpath}", f"-Djava.home={java_home}"]

        native_path = _resolve_comsol_native_path(settings)
        path_sep = ";" if os.name == "nt" else ":"
        if native_path:
            jvm_args.append(f"-Djava.library.path={native_path}")
            old_path = os.environ.get("PATH", "")
            if native_path not in old_path:
                os.environ["PATH"] = native_path + path_sep + old_path
            logger.info("COMSOL 本地库路径: %s", native_path)
        if comsol_jvm:
            jre_bin = Path(comsol_jvm).resolve().parent.parent
            if jre_bin.exists():
                prepend = str(jre_bin) + path_sep + os.environ.get("PATH", "")
                os.environ["PATH"] = prepend

        try:
            jpype = _jpype()
            jvm_path = comsol_jvm if comsol_jvm else jpype.getDefaultJVMPath()
            jpype.startJVM(jvm_path, *jvm_args)
            # 使用 JClass 加载，避免 "No module named 'com'"（com 为 Java 包，非 Python 模块）
            ModelUtil = jpype.JClass("com.comsol.model.util.ModelUtil")
            ModelUtil.initStandalone(False)
            logger.info("JVM 启动成功，COMSOL API 已加载")
            cls._jvm_started = True
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"加载 COMSOL API 失败: {e}")
            raise RuntimeError(f"无法加载 COMSOL API: {e}") from e

    def create_model(self, model_name: str):
        jpype = _jpype()
        ModelUtil = jpype.JClass("com.comsol.model.util.ModelUtil")
        logger.info(f"创建模型: {model_name}")
        return ModelUtil.create(model_name)

    # ===== 2D Shapes =====

    def create_rectangle(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "rect1"
        w, h = shape.parameters["width"], shape.parameters["height"]
        x, y = shape.position.get("x", 0.0), shape.position.get("y", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Rectangle")
        feat.set("size", [w, h])
        feat.set("pos", [x, y])

    def create_circle(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "circ1"
        r = shape.parameters["radius"]
        x, y = shape.position.get("x", 0.0), shape.position.get("y", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Circle")
        feat.set("r", r)
        feat.set("pos", [x, y])

    def create_ellipse(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "ell1"
        a, b = shape.parameters["a"], shape.parameters["b"]
        x, y = shape.position.get("x", 0.0), shape.position.get("y", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Ellipse")
        feat.set("a", a)
        feat.set("b", b)
        feat.set("pos", [x, y])

    def create_polygon(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "poly1"
        xs, ys = shape.parameters["x"], shape.parameters["y"]
        geom = self._geom(model)
        feat = geom.create(name, "Polygon")
        feat.set("x", xs)
        feat.set("y", ys)

    # ===== 3D Shapes =====

    def create_block(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "blk1"
        w = shape.parameters["width"]
        h = shape.parameters["height"]
        d = shape.parameters["depth"]
        x, y, z = shape.position.get("x", 0.0), shape.position.get("y", 0.0), shape.position.get("z", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Block")
        feat.set("size", [w, d, h])
        feat.set("pos", [x, y, z])

    def create_cylinder(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "cyl1"
        r, h = shape.parameters["radius"], shape.parameters["height"]
        x, y, z = shape.position.get("x", 0.0), shape.position.get("y", 0.0), shape.position.get("z", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Cylinder")
        feat.set("r", r)
        feat.set("h", h)
        feat.set("pos", [x, y, z])

    def create_sphere(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "sph1"
        r = shape.parameters["radius"]
        x, y, z = shape.position.get("x", 0.0), shape.position.get("y", 0.0), shape.position.get("z", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Sphere")
        feat.set("r", r)
        feat.set("pos", [x, y, z])

    def create_cone(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "cone1"
        rb = shape.parameters["radius_bottom"]
        rt = shape.parameters.get("radius_top", 0.0)
        h = shape.parameters["height"]
        x, y, z = shape.position.get("x", 0.0), shape.position.get("y", 0.0), shape.position.get("z", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Cone")
        feat.set("r", rb)
        feat.set("rtop", rt)
        feat.set("h", h)
        feat.set("pos", [x, y, z])

    def create_torus(self, model, shape: GeometryShape, name: Optional[str] = None) -> None:
        name = name or shape.name or "tor1"
        rmaj = shape.parameters["radius_major"]
        rmin = shape.parameters["radius_minor"]
        x, y, z = shape.position.get("x", 0.0), shape.position.get("y", 0.0), shape.position.get("z", 0.0)
        geom = self._geom(model)
        feat = geom.create(name, "Torus")
        feat.set("rmaj", rmaj)
        feat.set("rmin", rmin)
        feat.set("pos", [x, y, z])

    # ===== Dispatch =====

    _SHAPE_CREATORS = {
        "rectangle": "create_rectangle",
        "circle": "create_circle",
        "ellipse": "create_ellipse",
        "polygon": "create_polygon",
        "block": "create_block",
        "cylinder": "create_cylinder",
        "sphere": "create_sphere",
        "cone": "create_cone",
        "torus": "create_torus",
    }

    def create_shape(self, model, shape: GeometryShape, index: int = 1) -> None:
        creator_name = self._SHAPE_CREATORS.get(shape.type)
        if not creator_name:
            raise ValueError(f"不支持的形状类型: {shape.type}")
        getattr(self, creator_name)(model, shape)

    def _geom(self, model, geom_name: str = "geom1"):
        try:
            if model.component().has("comp1") and model.component("comp1").geom().has(geom_name):
                return model.component("comp1").geom(geom_name)
        except Exception:
            pass
        return model.geom(geom_name)

    def build_geometry(self, model, geom_name: str = "geom1") -> None:
        logger.info(f"构建几何: {geom_name}")
        geom = self._geom(model, geom_name)
        geom.run()

    def save_model(self, model, output_path: Path, copy_to_project: bool = True) -> Path:
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_path_str = output_path.as_posix()
        logger.info(f"保存模型到: {output_path}")
        model.save(save_path_str)

        if not output_path.exists():
            raise RuntimeError(f"模型保存失败: {output_path}")

        if copy_to_project:
            project_models = get_project_root() / "models"
            project_copy = project_models / output_path.name
            if project_copy.resolve() != output_path.resolve():
                project_models.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output_path, project_copy)
                logger.info(f"已同步保存到项目目录: {project_copy}")

        logger.info(f"模型已成功保存: {output_path}")
        return output_path

    def create_model_from_plan(self, plan: GeometryPlan, output_filename: Optional[str] = None, output_dir: Optional[Path] = None) -> Path:
        safe_name = (plan.model_name or "model").replace(" ", "_").strip() or "model"
        dimension = plan.dimension
        logger.info(f"根据计划创建 {dimension}D 模型: {safe_name}")

        model = self.create_model(safe_name)
        model.component().create("comp1")
        model.component("comp1").geom().create("geom1", dimension)

        for i, shape in enumerate(plan.shapes, 1):
            if not shape.name:
                shape.name = f"{shape.type}{i}"
            self.create_shape(model, shape, i)

        self.build_geometry(model, "geom1")

        if output_filename is None:
            output_filename = f"{safe_name}.mph"

        if output_dir is not None:
            output_path = Path(output_dir).resolve() / output_filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            output_path = Path(self.settings.model_output_dir) / output_filename
        save_path = self.save_model(model, output_path, copy_to_project=(output_dir is None))
        return save_path

    @classmethod
    def shutdown_jvm(cls):
        if cls._jvm_started:
            _jpype().shutdownJVM()
            cls._jvm_started = False
            logger.info("JVM 已关闭")
