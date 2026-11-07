"""Java API 控制器 - 混合模式控制 Java API 调用（支持材料、3D、扩展物理场）"""

import base64
import importlib.util
import re
import shutil
import tempfile
import threading
from datetime import datetime
from html import unescape
from pathlib import Path
from types import MethodType
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen
from uuid import uuid4

from agent.executor.comsol_runner import COMSOLRunner
from agent.executor.compute_backend import (
    detect_compute_backend,
    mark_solve_backend,
    should_attempt_gpu,
)
from agent.utils.config import get_settings
from agent.utils.logger import get_logger
from agent.schemas.material import MaterialDefinition, MaterialPlan
from agent.schemas.physics import PhysicsPlan
from agent.schemas.study import StudyPlan
from agent.schemas.task import GlobalDefinitionPlan, ModelOperationCase

logger = get_logger(__name__)
OFFICIAL_COMSOL_API_INDEX_URL = (
    "https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/api/index-all.html"
)


def _jpype():
    """延迟导入 jpype；缺包时在首次使用 COMSOL 时报错。"""
    try:
        import jpype

        return jpype
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "未找到 jpype 模块，COMSOL 功能需要安装 jpype1。请在项目根目录执行: uv sync 或 pip install jpype1"
        ) from e


PHYSICS_TYPE_TO_COMSOL_TAG = {
    "heat": "HeatTransfer",
    "electromagnetic": "ElectromagneticWaves",
    "structural": "SolidMechanics",
    "fluid": "SinglePhaseFlow",
    "acoustics": "Acoustics",
    "piezoelectric": "Piezoelectric",
    "chemical": "ChemicalSpeciesTransport",
    "multibody": "MultibodyDynamics",
}

STUDY_TYPE_TO_COMSOL_TAG = {
    "stationary": "Stationary",
    "time_dependent": "Time",
    "eigenvalue": "Eigenvalue",
    "frequency": "Frequency",
    "parametric": "Parametric",
}

COUPLING_TYPE_TO_COMSOL_TAG = {
    "thermal_stress": "ThermalExpansion",
    "fluid_structure": "FluidStructureInteraction",
    "electromagnetic_heat": "ElectromagneticHeat",
}

# COMSOL 线弹性/固体力学材料属性名：我们 schema 用 poissonsratio/youngsmodulus，API 用 nu/E
MATERIAL_PROPERTY_COMSOL_ALIAS = {
    "thermalconductivity": "k",
    "thermal conductivity": "k",
    "density": "rho",
    "specificheat": "Cp",
    "specific heat": "Cp",
    "poissonsratio": "nu",
    "youngsmodulus": "E",
}

# 固体传热所需导热系数 k 的典型值（W/(m·K)），避免「未定义固体1所需的材料属性k」
# 用于内置材料加载失败或自定义属性未含 k 时补全
THERMAL_K_BY_NAME = {
    "steel": 50.0,
    "钢": 50.0,
    "copper": 400.0,
    "铜": 400.0,
    "aluminum": 237.0,
    "铝": 237.0,
    "water": 0.6,
    "水": 0.6,
}
# 无法从名称推断时，固体域默认导热系数（W/(m·K)）
DEFAULT_THERMAL_K_SOLID = 50.0
DEFAULT_DENSITY_SOLID = 2700.0
DEFAULT_CP_SOLID = 900.0
# 线弹性材料默认 E/nu，避免「未定义线弹性材料所需的材料属性 nu/E」
DEFAULT_YOUNGS_MODULUS_SOLID = 200e9
DEFAULT_POISSONS_RATIO = 0.3

DENSITY_BY_NAME = {
    "steel": 7850.0,
    "copper": 8960.0,
    "aluminum": 2700.0,
    "water": 1000.0,
}

CP_BY_NAME = {
    "steel": 475.0,
    "copper": 385.0,
    "aluminum": 900.0,
    "water": 4180.0,
}

YOUNGS_MODULUS_BY_NAME = {
    "steel": 200e9,
    "copper": 110e9,
    "aluminum": 70e9,
    "aluminium": 70e9,
    "glass": 70e9,
    "titanium": 110e9,
}

POISSONS_RATIO_BY_NAME = {
    "steel": 0.3,
    "copper": 0.35,
    "aluminum": 0.33,
    "aluminium": 0.33,
    "glass": 0.22,
    "titanium": 0.34,
}


def _comsol_value(value: Any, unit: Optional[str] = None) -> str:
    """Format scalar values for COMSOL Java API set() overloads."""
    if isinstance(value, str):
        return value
    text = f"{value:g}" if isinstance(value, (int, float)) else str(value)
    if unit:
        return f"{text}[{unit}]"
    return text


def _physics_parameter_value(condition_type: str, key: str, value: Any) -> str:
    if isinstance(value, str):
        return value
    if condition_type in {"Temperature", "temperature"} and key in {"T0", "T", "Tamb"}:
        return _comsol_value(value, "K")
    if condition_type in {"ConvectiveHeatFlux", "convective_heat_flux"} and key in {
        "Text",
        "Tinf",
        "Tamb",
    }:
        return _comsol_value(value, "K")
    if condition_type in {"ConvectiveHeatFlux", "convective_heat_flux"} and key in {
        "h",
        "h0",
    }:
        return _comsol_value(value, "W/(m^2*K)")
    if condition_type in {"HeatFlux", "heat_flux"} and key in {"q0", "q"}:
        return _comsol_value(value, "W/m^2")
    return _comsol_value(value)


def _heat_boundary_feature_type(condition_type: str) -> str:
    return {
        "Temperature": "TemperatureBoundary",
        "temperature": "TemperatureBoundary",
        "HeatFlux": "HeatFluxBoundary",
        "heat_flux": "HeatFluxBoundary",
        # COMSOL 无独立 ConvectiveHeatFlux 特征：走 HeatFluxBoundary + HeatFluxType
        "ConvectiveHeatFlux": "HeatFluxBoundary",
        "convective_heat_flux": "HeatFluxBoundary",
        "ThermalInsulation": "ThermalInsulation",
        "thermal_insulation": "ThermalInsulation",
    }.get(condition_type, condition_type)


def _is_convective_heat_flux(condition_type: str) -> bool:
    return condition_type in {"ConvectiveHeatFlux", "convective_heat_flux"}


def _apply_physics_feature_selection(feature, selection: Any) -> None:
    """支持 list 面 ID，以及 \"all\"/\"exterior\" 字符串选择。"""
    if selection is None:
        return
    if isinstance(selection, str):
        token = selection.strip().lower()
        if token in {"all", "exterior", "*", "entire"}:
            feature.selection().all()
            return
        # 允许 "1,2,3" 或 "1 2 3"
        parts = [p for p in selection.replace(",", " ").split() if p.strip()]
        ids: List[int] = []
        for p in parts:
            try:
                ids.append(int(p))
            except ValueError:
                return
        if ids:
            feature.selection().set(ids)
        return
    if isinstance(selection, list) and selection:
        feature.selection().set(selection)


def _configure_heat_flux_boundary(feature, condition_type: str, parameters: Dict[str, Any]) -> None:
    """为 HeatFluxBoundary 配置一般热通量或对流换热。"""
    if _is_convective_heat_flux(condition_type):
        for key, val in (
            ("HeatFluxType", "ConvectiveHeatFlux"),
            ("heatFluxType", "ConvectiveHeatFlux"),
            ("HeatFluxType", "Convective"),
        ):
            try:
                feature.set(key, val)
                break
            except Exception:
                continue
        return
    if condition_type in {"HeatFlux", "heat_flux"}:
        for key, val in (
            ("HeatFluxType", "GeneralInwardHeatFlux"),
            ("heatFluxType", "GeneralInwardHeatFlux"),
            ("HeatFluxType", "InwardHeatFlux"),
        ):
            try:
                feature.set(key, val)
                break
            except Exception:
                continue


EMW_BOUNDARY_FEATURE_ALIASES = {
    # COMSOL releases/modules differ on whether the UI node name or the compact
    # physics feature tag is accepted by feature().create().
    "ScatteringBoundaryCondition": ["ScatteringBoundaryCondition", "Scattering"],
    "Scattering": ["Scattering", "ScatteringBoundaryCondition"],
    "PerfectElectricConductor": ["PerfectElectricConductor", "PerfectConductor"],
    "PerfectConductor": ["PerfectConductor", "PerfectElectricConductor"],
    "PerfectMagneticConductor": ["PerfectMagneticConductor"],
    "ImpedanceBoundaryCondition": ["ImpedanceBoundaryCondition", "ImpedanceBoundary"],
    "TransitionBoundaryCondition": ["TransitionBoundaryCondition", "TransitionBoundary"],
    "LayeredTransitionBoundaryCondition": ["LayeredTransitionBoundaryCondition"],
    "LayeredImpedanceBoundaryCondition": ["LayeredImpedanceBoundaryCondition"],
    "Port": ["Port"],
    "ElectricField": ["ElectricField"],
    "MagneticField": ["MagneticField"],
}

EMW_PML_CONDITION_TYPES = {
    "PML",
    "PerfectlyMatchedLayer",
    "PerfectlyMatchedLayers",
    "PerfectlyMatchedLayerBoundary",
    "perfectly_matched_layer",
}

EMW_INTERFACE_CONTINUITY_TYPES = {
    # These are descriptions of dielectric material interfaces, not valid EMW
    # boundary feature tags. For normal material interfaces, EMW continuity is
    # already the natural/default condition.
    "MultilayerDielectric",
    "MultiLayerDielectric",
    "DielectricInterface",
    "FresnelInterface",
    "MaterialInterface",
}

EMW_UNSUPPORTED_PARAMETER_KEYS = {
    # GUI/planner wording occasionally appears as a Java API property. It is not
    # a settable property on the EMW physics feature in common COMSOL versions.
    "SpecifyWave",
}


def _dedupe_ordered(values: List[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _emw_boundary_feature_candidates(condition_type: str) -> List[str]:
    return _dedupe_ordered(
        EMW_BOUNDARY_FEATURE_ALIASES.get(condition_type, [condition_type])
    )


def _is_unknown_parameter_error(exc: Exception) -> bool:
    msg = str(exc)
    return "Unknown parameter" in msg or "未知参数" in msg


def _physics_create_feature_with_candidates(
    physics_feature,
    feature_name: str,
    feature_types: List[str],
):
    last_exc = None
    for feature_type in feature_types:
        for entity_dim in (1, 2, None):
            try:
                if entity_dim is None:
                    physics_feature.create(feature_name, feature_type)
                else:
                    physics_feature.create(feature_name, feature_type, entity_dim)
                return feature_type
            except Exception as exc:
                last_exc = exc
                continue
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"No feature type candidates for {feature_name}")


def _set_feature_parameters_best_effort(
    feature,
    condition_type: str,
    parameters: Dict[str, Any],
    notes: List[Dict[str, Any]],
    *,
    scope: str,
    feature_name: str,
) -> None:
    for key, value in (parameters or {}).items():
        if key in EMW_UNSUPPORTED_PARAMETER_KEYS:
            notes.append(
                {
                    "kind": "skipped_parameter",
                    "scope": scope,
                    "name": feature_name,
                    "parameter": key,
                    "reason": "unsupported_by_comsol_java_api",
                }
            )
            continue
        try:
            feature.set(key, _physics_parameter_value(condition_type, key, value))
        except Exception as exc:
            if _is_unknown_parameter_error(exc):
                notes.append(
                    {
                        "kind": "skipped_parameter",
                        "scope": scope,
                        "name": feature_name,
                        "parameter": key,
                        "reason": str(exc),
                    }
                )
                continue
            raise


def _material_property_group(feat, preferred: str = "def"):
    tag = (preferred or "def").strip()
    if tag == "Def":
        tag = "def"
    try:
        return feat.propertyGroup(tag)
    except Exception:
        pass
    try:
        feat.propertyGroup().create(tag, "Basic")
        return feat.propertyGroup(tag)
    except Exception:
        return feat.propertyGroup("def")


def _ensure_material_thermal_k(feat, mat_def: MaterialDefinition) -> None:
    """为材料设置导热系数 k（若尚未设置），避免固体传热报「未定义固体1所需的材料属性k」。"""
    key = ""
    for part in (mat_def.builtin_name, mat_def.label, mat_def.name):
        if part:
            key = (part or "").strip().lower()
            break
    k_val = DEFAULT_THERMAL_K_SOLID
    for name, val in THERMAL_K_BY_NAME.items():
        if name in key or key in name:
            k_val = val
            break
    try:
        _material_property_group(feat).set("thermalconductivity", _comsol_value(k_val, "W/(m*K)"))
    except Exception:
        pass


def _material_lookup_value(
    mat_def: MaterialDefinition,
    table: Dict[str, float],
    default: float,
) -> float:
    key = ""
    for part in (mat_def.builtin_name, mat_def.label, mat_def.name):
        if part:
            key = (part or "").strip().lower()
            break
    for name, val in table.items():
        if name in key or key in name:
            return val
    return default


def _material_def_property_group(feat):
    """Resolve the Basic/def property group used by Heat Transfer and Solid Mechanics."""
    for group_name in ("def", "Def", "Basic", "basic"):
        try:
            return feat.propertyGroup(group_name)
        except Exception:
            continue
    return None


def _ensure_material_heat_properties(feat, mat_def: MaterialDefinition) -> None:
    """Write baseline heat-transfer material properties explicitly."""
    group = _material_def_property_group(feat)
    if group is None:
        logger.warning("材料属性组不可用，跳过热属性补齐")
        return

    values = {
        "k": _comsol_value(
            _material_lookup_value(mat_def, THERMAL_K_BY_NAME, DEFAULT_THERMAL_K_SOLID),
            "W/(m*K)",
        ),
        "rho": _comsol_value(
            _material_lookup_value(mat_def, DENSITY_BY_NAME, DEFAULT_DENSITY_SOLID),
            "kg/m^3",
        ),
        "Cp": _comsol_value(
            _material_lookup_value(mat_def, CP_BY_NAME, DEFAULT_CP_SOLID),
            "J/(kg*K)",
        ),
    }
    for name, value in values.items():
        try:
            group.set(name, value)
        except Exception as exc:
            logger.warning("设置材料热属性 %s 失败: %s", name, exc)


def _ensure_material_elastic_properties(feat, mat_def: MaterialDefinition) -> None:
    """补齐线弹性所需 E/nu，避免固体力学报「未定义线弹性材料所需的材料属性 nu」。"""
    group = _material_def_property_group(feat)
    if group is None:
        logger.warning("材料属性组不可用，跳过弹性属性补齐")
        return

    e_val = _material_lookup_value(
        mat_def, YOUNGS_MODULUS_BY_NAME, DEFAULT_YOUNGS_MODULUS_SOLID
    )
    nu_val = _material_lookup_value(
        mat_def, POISSONS_RATIO_BY_NAME, DEFAULT_POISSONS_RATIO
    )
    # 同时写短名与长名，兼容不同 COMSOL 版本 /「来自材料」解析
    values = {
        "E": _comsol_value(e_val, "Pa"),
        "nu": _comsol_value(nu_val),
        "youngsmodulus": _comsol_value(e_val, "Pa"),
        "poissonsratio": _comsol_value(nu_val),
    }
    for name, value in values.items():
        try:
            group.set(name, value)
        except Exception as exc:
            logger.warning("设置材料弹性属性 %s 失败: %s", name, exc)


def _save_model_avoid_lock(model, dest_path: Path, allow_fallback: bool = True):
    """保存 model 到 dest_path。优先直接覆盖原路径（避免自进程占用导致 replace 失败）；否则先写临时再替换或落备用路径。"""
    import os
    import time

    dest_path = Path(dest_path).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # 同一进程内从该路径加载的模型往往仍占用该文件，用临时文件再 replace 会报共享冲突。先尝试直接保存到目标路径。
    try:
        model.save(dest_path.as_posix())
        return dest_path
    except Exception:
        pass

    fd, tmp_path = tempfile.mkstemp(
        suffix=".mph", prefix=dest_path.stem + "_", dir=str(dest_path.parent)
    )
    try:
        os.close(fd)
    except Exception:
        pass
    tmp_path = Path(tmp_path)
    try:
        model.save(tmp_path.as_posix())
        for attempt in range(3 if not allow_fallback else 1):
            try:
                tmp_path.replace(dest_path)
                return dest_path
            except OSError as e:
                if getattr(e, "winerror", None) != 32:
                    raise
                if allow_fallback:
                    fallback = dest_path.parent / (dest_path.stem + "_updated.mph")
                    shutil.copy2(str(tmp_path), str(fallback))
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                    logger.info(f"原文件被占用，已保存到: {fallback}")
                    return fallback
                if attempt < 2:
                    time.sleep(0.5)
                    continue
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
                raise RuntimeError(f"模型文件被占用，无法保存到: {dest_path}") from e
        return None
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


def _save_model_to_new_path(model, dest_path: Path) -> Path:
    """保存到新路径（非覆盖），避免占用冲突。用于按阶段命名时每步写入新文件。"""
    dest_path = Path(dest_path).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(dest_path.as_posix())
    return dest_path


class JavaAPIController:
    """Java API 控制器 - 根据操作复杂度选择直接调用或代码生成"""

    def __init__(self):
        self.settings = get_settings()
        self.comsol_runner: Optional[COMSOLRunner] = None
        self._official_api_entries: Optional[List[Dict[str, str]]] = None
        self._official_api_wrappers: Dict[str, Dict[str, str]] = {}
        wrappers_path = Path(__file__).resolve().parent / "comsol_official_api_wrappers.py"
        if wrappers_path.exists():
            try:
                self.load_official_api_wrapper_module(str(wrappers_path))
            except Exception as e:
                logger.warning("加载静态官方 API 包装模块失败: %s", e)

    # ===== Model load helper =====

    def _load_model(self, model_path: str):
        COMSOLRunner._ensure_jvm_started()
        jpype = _jpype()
        # 使用 JClass 加载，避免 "No module named 'com'"（com 为 Java 包，非 Python 模块）
        ModelUtil = jpype.JClass("com.comsol.model.util.ModelUtil")
        path = Path(model_path)
        return ModelUtil.load(path.stem or "model", str(path.resolve()))

    def _get_comsol_runner(self) -> COMSOLRunner:
        if self.comsol_runner is None:
            self.comsol_runner = COMSOLRunner()
        return self.comsol_runner

    # ===== Materials =====

    @staticmethod
    def _materials_api(model):
        """获取材料的 API：COMSOL 部分版本为 model.material()（单数），部分为 model.materials()（复数）。
        若在 component 下，则用 model.component('comp1').material()。不支持时直接抛错并中断。"""
        try:
            if hasattr(model, "materials"):
                return model.materials()
            if hasattr(model, "material"):
                return model.material()
        except Exception as e:
            raise RuntimeError(f"COMSOL 材料 API 不可用: {e}") from e
        try:
            if self._node_list_has(model.component(), "comp1") and hasattr(model.component("comp1"), "material"):
                return model.component("comp1").material()
        except Exception as e:
            raise RuntimeError(f"COMSOL 材料 API 不可用（component.material）: {e}") from e
        raise RuntimeError(
            "当前 COMSOL 模型对象无 material()/materials() 接口，请确认 COMSOL 版本与 API。"
        )

    def _material_feature(self, model, name: str):
        """获取名为 name 的材料节点。先尝试 model 级，再尝试 component 级。"""
        try:
            if hasattr(model, "materials"):
                return model.materials(name)
            if hasattr(model, "material"):
                return model.material(name)
        except Exception as e:
            raise RuntimeError(f"获取材料节点 '{name}' 失败: {e}") from e
        try:
            if self._node_list_has(model.component(), "comp1"):
                return model.component("comp1").material(name)
        except Exception as e:
            raise RuntimeError(f"获取材料节点 '{name}' 失败: {e}") from e
        raise RuntimeError("当前 COMSOL 模型不支持材料节点访问")

    def _physics_api(self, model):
        """获取物理场 API：component 下用 component('comp1').physics()，否则用 model.physics()。"""
        try:
            if self._node_list_has(model.component(), "comp1") and hasattr(model.component("comp1"), "physics"):
                return model.component("comp1").physics()
        except Exception:
            pass
        if hasattr(model, "physics"):
            return model.physics()
        raise RuntimeError("当前 COMSOL 模型无 physics() 接口")

    def _physics_feature(self, model, name: str):
        """获取名为 name 的物理场节点。与 _physics_api 同源（component 或 root）。"""
        try:
            if self._node_list_has(model.component(), "comp1") and hasattr(model.component("comp1"), "physics"):
                return model.component("comp1").physics(name)
        except Exception:
            pass
        return model.physics(name)

    # ===== 材料节点：查询 / 删除 / 重命名 / 存在检查 / 更新属性 / 批量删除 =====

    def _component_api(self, model):
        try:
            if self._node_list_has(model.component(), "comp1"):
                return model.component("comp1")
        except Exception:
            pass
        return None

    def list_material_tags(self, model_path: str) -> Dict[str, Any]:
        """查询模型中现有材料节点名称列表。API: model.material().names() 或 .tags()。"""
        try:
            model = self._load_model(model_path)
            mat_seq = self._materials_api(model)
            tags = self._tags_or_names(mat_seq)
            return {"status": "success", "tags": tags, "names": tags}
        except Exception as e:
            logger.warning("list_material_tags 失败: %s", e)
            return {"status": "error", "message": str(e), "tags": [], "names": []}

    def list_material_names(self, model_path: str) -> Dict[str, Any]:
        """查询材料名称列表。API: model.material().names() 或 .tags()。"""
        return self.list_material_tags(model_path)

    def remove_material(self, model_path: str, name: str) -> Dict[str, Any]:
        """删除指定名称的材料节点。API: model.material().remove(\"mat1\")."""
        try:
            model = self._load_model(model_path)
            mat_seq = self._materials_api(model)
            if hasattr(mat_seq, "remove"):
                mat_seq.remove(name)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 materials().remove()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已删除材料 {name}", "removed": name}
        except Exception as e:
            logger.warning("remove_material 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def has_material(self, model_path: str, name: str) -> Dict[str, Any]:
        """检查材料节点是否存在。API: model.material().has(\"mat1\") 或 names()/tags() 包含。"""
        try:
            model = self._load_model(model_path)
            mat_seq = self._materials_api(model)
            if hasattr(mat_seq, "has"):
                exists = mat_seq.has(name)
            else:
                exists = name in self._tags_or_names(mat_seq)
            return {"status": "success", "exists": bool(exists)}
        except Exception as e:
            logger.warning("has_material 失败: %s", e)
            return {"status": "error", "message": str(e), "exists": False}

    def rename_material(self, model_path: str, old_name: str, new_name: str) -> Dict[str, Any]:
        """重命名材料节点。COMSOL 部分版本无直接 rename，采用“创建新名 + 复制属性 + 删除旧”实现。"""
        try:
            model = self._load_model(model_path)
            mat_seq = self._materials_api(model)
            if not (hasattr(mat_seq, "has") and mat_seq.has(old_name)):
                return {"status": "error", "message": f"材料节点不存在: {old_name}"}
            if hasattr(mat_seq, "has") and mat_seq.has(new_name):
                return {"status": "error", "message": f"目标名称已存在: {new_name}"}
            feat_old = self._material_feature(model, old_name)
            mat_seq.create(new_name)
            feat_new = self._material_feature(model, new_name)
            try:
                if hasattr(feat_old, "label"):
                    feat_new.label(feat_old.get("label") or new_name)
            except Exception:
                pass
            try:
                if hasattr(feat_old, "getString") and hasattr(feat_new, "set"):
                    for key in ("family", "materialType"):
                        try:
                            v = feat_old.getString(key)
                            if v:
                                feat_new.set(key, v)
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                if hasattr(feat_old, "propertyGroup"):
                    for g in ("Def", "SolidMechanics", "Thermal"):
                        try:
                            pg_old = feat_old.propertyGroup(g)
                            pg_new = feat_new.propertyGroup(g)
                            for prop in (
                                "nu",
                                "E",
                                "density",
                                "thermalconductivity",
                                "specificheat",
                                "youngsmodulus",
                                "poissonsratio",
                            ):
                                try:
                                    val = pg_old.get(prop)
                                    if val is not None:
                                        pg_new.set(prop, val)
                                except Exception:
                                    pass
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                if hasattr(feat_old, "selection") and hasattr(feat_new, "selection"):
                    feat_new.selection().set(feat_old.selection().entities())
            except Exception:
                pass
            if hasattr(mat_seq, "remove"):
                mat_seq.remove(old_name)
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已重命名 {old_name} -> {new_name}",
                "old_name": old_name,
                "new_name": new_name,
            }
        except Exception as e:
            logger.warning("rename_material 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def update_material_properties(
        self, model_path: str, name: str, properties: Dict[str, Any], property_group: str = "Def"
    ) -> Dict[str, Any]:
        """更新现有材料属性。API: model.material(\"mat1\").propertyGroup(\"def\").set(\"property\", value)。
        支持 property_group 为 Def / def、SolidMechanics、Thermal 等。"""
        try:
            model = self._load_model(model_path)
            feat = self._material_feature(model, name)
            group = (property_group or "Def").strip()
            if group.lower() == "def":
                group = "Def"
            for k, v in properties.items():
                key = MATERIAL_PROPERTY_COMSOL_ALIAS.get(k, k)
                done = False
                if hasattr(feat, "property"):
                    try:
                        feat.property(key, v)
                        done = True
                    except Exception:
                        try:
                            feat.property(k, v)
                            done = True
                        except Exception:
                            pass
                if not done:
                    try:
                        pg = feat.propertyGroup(group)
                        pg.set(key, v)
                    except Exception:
                        try:
                            pg.set(k, v)
                        except Exception as e2:
                            logger.warning("设置属性 %s 失败: %s", k, e2)
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已更新材料 {name} 属性", "material": name}
        except Exception as e:
            logger.warning("update_material_properties 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def remove_all_materials(self, model_path: str) -> Dict[str, Any]:
        """清除模型中所有材料节点（批量删除）。API: model.material().remove(tag) 逐项。"""
        try:
            model = self._load_model(model_path)
            mat_seq = self._materials_api(model)
            tags = self._tags_or_names(mat_seq)
            if not hasattr(mat_seq, "remove"):
                return {
                    "status": "error",
                    "message": "当前 COMSOL 版本不支持 materials().remove()",
                    "removed": [],
                }
            for tag in tags:
                try:
                    mat_seq.remove(tag)
                except Exception as e:
                    logger.warning("删除材料 %s 失败: %s", tag, e)
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已删除 {len(tags)} 个材料节点",
                "removed": tags,
            }
        except Exception as e:
            logger.warning("remove_all_materials 失败: %s", e)
            return {"status": "error", "message": str(e), "removed": []}

    def list_model_tree(self, model_path: str) -> Dict[str, Any]:
        """获取模型树中主要节点信息（材料、物理场、研究、网格、几何）。
        兼容 model.xxx().tags() 与 model.xxx().names()。"""
        out = {
            "materials": [],
            "physics": [],
            "studies": [],
            "meshes": [],
            "geometries": [],
            "results": [],
        }
        try:
            model = self._load_model(model_path)
            try:
                ms = self._materials_api(model)
                out["materials"] = self._tags_or_names(ms)
            except Exception:
                pass
            try:
                ph = self._physics_api(model)
                out["physics"] = self._tags_or_names(ph)
            except Exception:
                pass
            try:
                if hasattr(model, "study"):
                    out["studies"] = self._tags_or_names(model.study())
            except Exception:
                pass
            try:
                if hasattr(model, "mesh"):
                    out["meshes"] = self._tags_or_names(model.mesh())
            except Exception:
                pass
            try:
                if self._node_list_has(model.component(), "comp1") and hasattr(
                    model.component("comp1").geom(), "tags"
                ):
                    out["geometries"] = self._tags_or_names(model.component("comp1").geom())
                elif hasattr(model, "geom"):
                    out["geometries"] = self._tags_or_names(model.geom())
            except Exception:
                pass
            try:
                if hasattr(model, "result"):
                    out["results"] = self._tags_or_names(model.result())
            except Exception:
                pass
            return {"status": "success", "tree": out}
        except Exception as e:
            logger.warning("list_model_tree 失败: %s", e)
            return {"status": "error", "message": str(e), "tree": out}

    @staticmethod
    def _tags_or_names(seq) -> List[str]:
        """COMSOL 部分版本用 .names()，部分用 .tags()，统一返回名称列表。"""
        if hasattr(seq, "names"):
            try:
                n = seq.names()
                if n is not None:
                    return [str(x) for x in n]
            except Exception:
                pass
        if hasattr(seq, "tags"):
            try:
                t = seq.tags()
                if t is not None:
                    return [str(x) for x in t]
            except Exception:
                pass
        return []

    def _node_list_has(self, seq, name: str) -> bool:
        """检查节点列表是否包含 name。兼容无 .has() 的 ModelNodeListClient/GeomListClient 等。"""
        if seq is None:
            return False
        if hasattr(seq, "has"):
            try:
                return bool(seq.has(name))
            except Exception:
                pass
        return name in self._tags_or_names(seq)

    # ===== 研究节点：删除 / 查询名称 / 重命名 =====

    def remove_study(self, model_path: str, name: str) -> Dict[str, Any]:
        """删除研究节点。API: model.study().remove(\"std1\")."""
        try:
            model = self._load_model(model_path)
            st = model.study()
            if hasattr(st, "remove"):
                st.remove(name)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 study().remove()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已删除研究 {name}", "removed": name}
        except Exception as e:
            logger.warning("remove_study 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def clear_study(self, model_path: str) -> Dict[str, Any]:
        """清除模型中所有研究节点。API: model.study().remove(tag) 逐项。"""
        try:
            model = self._load_model(model_path)
            st = model.study()
            names = self._tags_or_names(st)
            if not hasattr(st, "remove"):
                return {
                    "status": "error",
                    "message": "当前 COMSOL 版本不支持 study().remove()",
                    "removed": [],
                }
            for name in names:
                try:
                    st.remove(name)
                except Exception as e:
                    logger.warning("删除研究 %s 失败: %s", name, e)
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已删除 {len(names)} 个研究节点",
                "removed": names,
            }
        except Exception as e:
            logger.warning("clear_study 失败: %s", e)
            return {"status": "error", "message": str(e), "removed": []}

    def list_study_names(self, model_path: str) -> Dict[str, Any]:
        """查询现有研究名称。API: model.study().names() 或 .tags()。"""
        try:
            model = self._load_model(model_path)
            st = model.study()
            names = self._tags_or_names(st)
            return {"status": "success", "names": names}
        except Exception as e:
            logger.warning("list_study_names 失败: %s", e)
            return {"status": "error", "message": str(e), "names": []}

    def rename_study(self, model_path: str, old_name: str, new_name: str) -> Dict[str, Any]:
        """重命名研究节点。API: model.study(\"std1\").name(\"newName\")."""
        try:
            model = self._load_model(model_path)
            st = model.study()
            if hasattr(st, "has") and not st.has(old_name):
                return {"status": "error", "message": f"研究节点不存在: {old_name}"}
            if hasattr(st, "has") and st.has(new_name):
                return {"status": "error", "message": f"目标名称已存在: {new_name}"}
            feat = model.study(old_name)
            if hasattr(feat, "name"):
                feat.name(new_name)
            else:
                return {
                    "status": "error",
                    "message": "当前 COMSOL 版本不支持 study(tag).name(newName)",
                }
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已重命名研究 {old_name} -> {new_name}",
                "old_name": old_name,
                "new_name": new_name,
            }
        except Exception as e:
            logger.warning("rename_study 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def has_node(self, model_path: str, node_path: str) -> Dict[str, Any]:
        """检查节点是否存在。API: model.hasNode(\"/studies/std1\"). 路径格式如 /studies/std1, /physics/ht0。"""
        try:
            model = self._load_model(model_path)
            path = (node_path or "").strip()
            if not path.startswith("/"):
                path = "/" + path
            if hasattr(model, "hasNode"):
                exists = model.hasNode(path)
            else:
                return {
                    "status": "error",
                    "message": "当前 COMSOL 版本不支持 hasNode(path)",
                    "exists": False,
                }
            return {"status": "success", "exists": bool(exists), "path": path}
        except Exception as e:
            logger.warning("has_node 失败: %s", e)
            return {"status": "error", "message": str(e), "exists": False}

    def clear_all_results(self, model_path: str) -> Dict[str, Any]:
        """清除所有结果数据。API: model.result().clearAll()。"""
        try:
            model = self._load_model(model_path)
            if not hasattr(model, "result"):
                return {"status": "error", "message": "当前 COMSOL 模型无 result() 接口"}
            res = model.result()
            if hasattr(res, "clearAll"):
                res.clearAll()
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 result().clearAll()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": "已清除所有结果数据"}
        except Exception as e:
            logger.warning("clear_all_results 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def get_node_tree(self, model_path: str) -> Dict[str, Any]:
        """获取模型树结构。API: model.getNodeTree()。若不存在则回退到 list_model_tree。"""
        try:
            model = self._load_model(model_path)
            if hasattr(model, "getNodeTree"):
                tree = model.getNodeTree()
                # 若返回 Java 对象，尝试转为可序列化结构
                if tree is not None and hasattr(tree, "toString"):
                    return {"status": "success", "node_tree": tree.toString()}
                return {"status": "success", "node_tree": tree}
            return self.list_model_tree(model_path)
        except Exception as e:
            logger.warning("get_node_tree 失败: %s", e)
            return {"status": "error", "message": str(e), "node_tree": None}

    # ===== 物理场节点：查询 / 删除 / 存在检查 =====

    def list_physics_tags(self, model_path: str) -> Dict[str, Any]:
        """获取所有物理场名称列表。API: model.physics().names() 或 .tags()。"""
        try:
            model = self._load_model(model_path)
            ph = self._physics_api(model)
            tags = self._tags_or_names(ph)
            return {"status": "success", "tags": tags, "names": tags}
        except Exception as e:
            return {"status": "error", "message": str(e), "tags": [], "names": []}

    def list_physics_names(self, model_path: str) -> Dict[str, Any]:
        """查询物理场名称列表。API: model.physics().names() 或 .tags()。"""
        return self.list_physics_tags(model_path)

    def remove_physics(self, model_path: str, name: str) -> Dict[str, Any]:
        """删除已存在的物理场节点。API: model.physics().remove(\"ht0\")."""
        try:
            model = self._load_model(model_path)
            ph = self._physics_api(model)
            if hasattr(ph, "remove"):
                ph.remove(name)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 physics().remove()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已删除物理场 {name}", "removed": name}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def has_physics(self, model_path: str, name: str) -> Dict[str, Any]:
        """检查物理场节点是否存在。API: model.physics().has(\"phys1\") 或 names()/tags() 包含。"""
        try:
            model = self._load_model(model_path)
            ph = self._physics_api(model)
            if hasattr(ph, "has"):
                exists = ph.has(name)
            else:
                exists = name in self._tags_or_names(ph)
            return {"status": "success", "exists": bool(exists)}
        except Exception as e:
            return {"status": "error", "message": str(e), "exists": False}

    def rename_physics(self, model_path: str, old_name: str, new_name: str) -> Dict[str, Any]:
        """重命名物理场节点。API: model.physics(\"ht0\").name(\"newName\")."""
        try:
            model = self._load_model(model_path)
            ph = self._physics_api(model)
            if hasattr(ph, "has") and not ph.has(old_name):
                return {"status": "error", "message": f"物理场节点不存在: {old_name}"}
            if hasattr(ph, "has") and ph.has(new_name):
                return {"status": "error", "message": f"目标名称已存在: {new_name}"}
            feat = self._physics_feature(model, old_name)
            if hasattr(feat, "name"):
                feat.name(new_name)
            else:
                return {
                    "status": "error",
                    "message": "当前 COMSOL 版本不支持 physics(tag).name(newName)",
                }
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已重命名物理场 {old_name} -> {new_name}",
                "old_name": old_name,
                "new_name": new_name,
            }
        except Exception as e:
            logger.warning("rename_physics 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def clear_physics(self, model_path: str) -> Dict[str, Any]:
        """清除所有物理场节点。API: model.physics().clear()."""
        try:
            model = self._load_model(model_path)
            ph = self._physics_api(model)
            if hasattr(ph, "clear"):
                ph.clear()
            else:
                tags = self._tags_or_names(ph)
                if hasattr(ph, "remove"):
                    for tag in tags:
                        try:
                            ph.remove(tag)
                        except Exception as e:
                            logger.warning("删除物理场 %s 失败: %s", tag, e)
                else:
                    return {
                        "status": "error",
                        "message": "当前 COMSOL 版本不支持 physics().clear() 或 remove()",
                    }
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": "已清除所有物理场节点"}
        except Exception as e:
            logger.warning("clear_physics 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def physics_feature_is_active(
        self, model_path: str, physics_tag: str, feature_tag: str
    ) -> Dict[str, Any]:
        """检查物理场下某特征是否已激活。API: model.physics(\"ht0\").feature(\"temp1\").isActive()."""
        try:
            model = self._load_model(model_path)
            feat = self._physics_feature(model, physics_tag).feature(feature_tag)
            active = feat.isActive() if hasattr(feat, "isActive") else True
            return {
                "status": "success",
                "active": bool(active),
                "physics": physics_tag,
                "feature": feature_tag,
            }
        except Exception as e:
            logger.warning("physics_feature_is_active 失败: %s", e)
            return {"status": "error", "message": str(e), "active": False}

    def set_physics_feature_param(
        self, model_path: str, physics_tag: str, feature_tag: str, key: str, value: Any
    ) -> Dict[str, Any]:
        """修改已存在边界条件/特征参数。API: model.physics(\"ht0\").feature(\"temp1\").set(\"T0\", \"293.15\")."""
        try:
            model = self._load_model(model_path)
            feat = self._physics_feature(model, physics_tag).feature(feature_tag)
            feat.set(key, value)
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已设置 {physics_tag}.{feature_tag}.{key}",
                "physics": physics_tag,
                "feature": feature_tag,
                "key": key,
            }
        except Exception as e:
            logger.warning("set_physics_feature_param 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== 几何节点：查询 =====

    def list_geometry_tags(self, model_path: str) -> Dict[str, Any]:
        """查询几何节点名称列表。API: model.geom().names() 或 .tags()；component 下为 component('comp1').geom()。"""
        try:
            model = self._load_model(model_path)
            if self._node_list_has(model.component(), "comp1"):
                geom_seq = model.component("comp1").geom()
            else:
                geom_seq = model.geom()
            tags = self._tags_or_names(geom_seq)
            return {"status": "success", "tags": tags, "names": tags}
        except Exception as e:
            return {"status": "error", "message": str(e), "tags": [], "names": []}

    def rename_geometry(self, model_path: str, old_name: str, new_name: str) -> Dict[str, Any]:
        """重命名几何节点。API: model.geom(\"geom1\").name(\"newGeomName\")。component 下为 component('comp1').geom(\"geom1\").name(\"newName\")。"""
        try:
            model = self._load_model(model_path)
            geom_seq = None
            if self._node_list_has(model.component(), "comp1"):
                geom_seq = model.component("comp1").geom()
            if geom_seq is None or not hasattr(geom_seq, "has"):
                geom_seq = model.geom()
            if not self._node_list_has(geom_seq, old_name):
                return {"status": "error", "message": f"几何节点不存在: {old_name}"}
            if self._node_list_has(geom_seq, new_name):
                return {"status": "error", "message": f"目标名称已存在: {new_name}"}
            if self._node_list_has(model.component(), "comp1"):
                feat = model.component("comp1").geom(old_name)
            else:
                feat = model.geom(old_name)
            if hasattr(feat, "name"):
                feat.name(new_name)
            else:
                return {
                    "status": "error",
                    "message": "当前 COMSOL 版本不支持 geom(tag).name(newName)",
                }
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已重命名几何 {old_name} -> {new_name}",
                "old_name": old_name,
                "new_name": new_name,
            }
        except Exception as e:
            logger.warning("rename_geometry 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== Selection（选择集）=====

    def _selection_api(self, model):
        """获取 selection 列表 API：model.selection() 或 component 下 component('comp1').selection()。"""
        try:
            if hasattr(model, "selection"):
                return model.selection()
            if self._node_list_has(model.component(), "comp1") and hasattr(model.component("comp1"), "selection"):
                return model.component("comp1").selection()
        except Exception as e:
            raise RuntimeError(f"COMSOL selection API 不可用: {e}") from e
        raise RuntimeError("当前 COMSOL 模型无 selection() 接口")

    def create_selection(
        self,
        model_path: str,
        tag: str,
        kind: str = "Explicit",
        geom_tag: str = "geom1",
        entity_dim: Optional[int] = None,
        entities: Optional[List[int]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """创建选择集。API: model.selection().create(tag, \"Explicit\")，再设置 geom/entities 或 all()。"""
        try:
            model = self._load_model(model_path)
            sel_list = self._selection_api(model)
            if hasattr(sel_list, "has") and sel_list.has(tag):
                return {"status": "error", "message": f"选择集已存在: {tag}"}
            sel_list.create(tag, kind or "Explicit")
            sel = (
                sel_list.get(tag)
                if hasattr(sel_list, "get")
                else getattr(sel_list, tag)
                if hasattr(sel_list, tag)
                else None
            )
            if sel is None and hasattr(sel_list, "tags"):
                tags = self._tags_or_names(sel_list)
                if tag in tags:
                    sel = sel_list(tag) if callable(sel_list) else None
            if sel is not None:
                if hasattr(sel, "geom"):
                    sel.geom(geom_tag)
                if entity_dim is not None and hasattr(sel, "set") and entities is not None:
                    try:
                        sel.set(entities)
                    except Exception:
                        pass
                elif kwargs.get("all") and hasattr(sel, "all"):
                    try:
                        sel.all()
                    except Exception:
                        pass
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已创建选择集 {tag}", "tag": tag}
        except Exception as e:
            logger.warning("create_selection 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def list_selection_tags(self, model_path: str) -> Dict[str, Any]:
        """查询选择集标签列表。"""
        try:
            model = self._load_model(model_path)
            sel_list = self._selection_api(model)
            tags = self._tags_or_names(sel_list)
            return {"status": "success", "tags": tags}
        except Exception as e:
            logger.warning("list_selection_tags 失败: %s", e)
            return {"status": "error", "message": str(e), "tags": []}

    def remove_selection(self, model_path: str, tag: str) -> Dict[str, Any]:
        """删除选择集。API: model.selection().remove(tag)。"""
        try:
            model = self._load_model(model_path)
            sel_list = self._selection_api(model)
            if hasattr(sel_list, "remove"):
                sel_list.remove(tag)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 selection().remove()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已删除选择集 {tag}", "removed": tag}
        except Exception as e:
            logger.warning("remove_selection 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def rename_selection(self, model_path: str, old_name: str, new_name: str) -> Dict[str, Any]:
        """重命名选择集（无直接 API 时用“复制+删除”策略；若支持 name/label 则直接设置）。"""
        try:
            model = self._load_model(model_path)
            sel_list = self._selection_api(model)
            if hasattr(sel_list, "has") and not sel_list.has(old_name):
                return {"status": "error", "message": f"选择集不存在: {old_name}"}
            if hasattr(sel_list, "has") and sel_list.has(new_name):
                return {"status": "error", "message": f"目标名称已存在: {new_name}"}
            sel = sel_list(old_name) if callable(sel_list) else sel_list.get(old_name)
            if sel is not None and hasattr(sel, "name"):
                sel.name(new_name)
            elif hasattr(sel_list, "remove"):
                sel_list.create(new_name, "Explicit")
                try:
                    new_sel = sel_list(new_name) if callable(sel_list) else sel_list.get(new_name)
                    if new_sel is not None and hasattr(sel, "entities") and hasattr(new_sel, "set"):
                        new_sel.set(sel.entities())
                except Exception:
                    pass
                sel_list.remove(old_name)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持选择集重命名"}
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已重命名选择集 {old_name} -> {new_name}",
                "old_name": old_name,
                "new_name": new_name,
            }
        except Exception as e:
            logger.warning("rename_selection 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== 几何 IO / 几何工具 =====

    def import_geometry(
        self,
        model_path: str,
        file_path: str,
        geom_tag: str = "geom1",
        feature_tag: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """导入几何文件（STEP/IGES/STL 等）。在 geom 下创建 Import 特征并 run()。"""
        try:
            model = self._load_model(model_path)
            path = Path(file_path)
            if not path.is_absolute():
                path = Path(model_path).parent / path
            if not path.exists():
                return {"status": "error", "message": f"文件不存在: {path}"}
            geom_seq = (
                model.component("comp1").geom() if self._node_list_has(model.component(), "comp1") else model.geom()
            )
            if not self._node_list_has(geom_seq, geom_tag):
                return {"status": "error", "message": f"几何节点不存在: {geom_tag}"}
            geom = (
                model.component("comp1").geom(geom_tag)
                if self._node_list_has(model.component(), "comp1")
                else model.geom(geom_tag)
            )
            feat_tag = feature_tag or "imp1"
            geom.create(feat_tag, "Import")
            imp = geom.feature(feat_tag)
            imp.set("filename", str(path.resolve()))
            for k, v in kwargs.items():
                try:
                    imp.set(k, v)
                except Exception:
                    pass
            geom.run()
            _save_model_avoid_lock(model, Path(model_path))
            return {
                "status": "success",
                "message": f"已导入几何 {path.name}",
                "feature": feat_tag,
                "path": str(path),
            }
        except Exception as e:
            logger.warning("import_geometry 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def geometry_measure(
        self,
        model_path: str,
        geom_tag: str = "geom1",
        what: str = "volume",
        selection: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """几何测量（体积/面积/长度等）。使用 COMSOL measure 工具；不可用时返回明确错误。"""
        try:
            model = self._load_model(model_path)
            geom_seq = (
                model.component("comp1").geom() if self._node_list_has(model.component(), "comp1") else model.geom()
            )
            if not self._node_list_has(geom_seq, geom_tag):
                return {"status": "error", "message": f"几何节点不存在: {geom_tag}"}
            geom = (
                model.component("comp1").geom(geom_tag)
                if self._node_list_has(model.component(), "comp1")
                else model.geom(geom_tag)
            )
            if not hasattr(geom, "measure"):
                return {"status": "error", "message": "当前 COMSOL 版本不支持 geom.measure()"}
            measure = geom.measure()
            if (
                not hasattr(measure, "getVolume")
                and not hasattr(measure, "getArea")
                and not hasattr(measure, "getLength")
            ):
                return {"status": "error", "message": "measure 接口无 getVolume/getArea/getLength"}
            if selection:
                try:
                    measure.selection().set(selection)
                except Exception:
                    pass
            value = None
            what_lower = (what or "volume").lower()
            if "volume" in what_lower and hasattr(measure, "getVolume"):
                value = measure.getVolume()
            elif "area" in what_lower and hasattr(measure, "getArea"):
                value = measure.getArea()
            elif "length" in what_lower and hasattr(measure, "getLength"):
                value = measure.getLength()
            if value is None:
                return {"status": "error", "message": f"不支持的测量类型: {what}"}
            return {
                "status": "success",
                "value": float(value) if value is not None else None,
                "what": what,
            }
        except Exception as e:
            logger.warning("geometry_measure 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== 网格高级 =====

    def _mesh_api(self, model):
        """获取 mesh 列表：model.mesh() 或 component('comp1').mesh()。"""
        try:
            if self._node_list_has(model.component(), "comp1") and hasattr(model.component("comp1"), "mesh"):
                return model.component("comp1").mesh()
            if hasattr(model, "mesh"):
                return model.mesh()
        except Exception as e:
            raise RuntimeError(f"COMSOL mesh API 不可用: {e}") from e
        raise RuntimeError("当前 COMSOL 模型无 mesh() 接口")

    def mesh_create(
        self, model_path: str, tag: str = "mesh1", geom_tag: str = "geom1"
    ) -> Dict[str, Any]:
        """创建网格序列。API: model.component('comp1').mesh().create(tag, geom_tag)。"""
        try:
            model = self._load_model(model_path)
            mesh_list = self._mesh_api(model)
            if self._mesh_has(mesh_list, tag):
                return {"status": "success", "message": f"网格已存在: {tag}", "tag": tag}
            mesh_list.create(tag, geom_tag)
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已创建网格 {tag}", "tag": tag}
        except Exception as e:
            logger.warning("mesh_create 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def mesh_list(self, model_path: str) -> Dict[str, Any]:
        """列出网格标签。"""
        try:
            model = self._load_model(model_path)
            mesh_list = self._mesh_api(model)
            tags = self._tags_or_names(mesh_list)
            return {"status": "success", "tags": tags}
        except Exception as e:
            logger.warning("mesh_list 失败: %s", e)
            return {"status": "error", "message": str(e), "tags": []}

    def mesh_remove(self, model_path: str, tag: str) -> Dict[str, Any]:
        """删除网格序列。"""
        try:
            model = self._load_model(model_path)
            mesh_list = self._mesh_api(model)
            if hasattr(mesh_list, "remove"):
                mesh_list.remove(tag)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 mesh().remove()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已删除网格 {tag}", "removed": tag}
        except Exception as e:
            logger.warning("mesh_remove 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def mesh_set_size(
        self,
        model_path: str,
        mesh_tag: str = "mesh1",
        hauto: Optional[int] = None,
        hmax: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """设置网格尺寸（Size 特征）。"""
        try:
            model = self._load_model(model_path)
            mesh_list = self._mesh_api(model)
            if not self._mesh_has(mesh_list, mesh_tag):
                return {"status": "error", "message": f"网格不存在: {mesh_tag}"}
            mesh = mesh_list(mesh_tag) if callable(mesh_list) else mesh_list.get(mesh_tag)
            try:
                mesh.create("size", "Size")
            except Exception:
                pass
            size_feat = mesh.feature("size") if hasattr(mesh, "feature") else None
            if size_feat is not None:
                if hauto is not None:
                    try:
                        size_feat.set("hauto", hauto)
                    except Exception:
                        pass
                if hmax is not None:
                    try:
                        size_feat.set("hmax", hmax)
                    except Exception:
                        pass
                for k, v in kwargs.items():
                    try:
                        size_feat.set(k, v)
                    except Exception:
                        pass
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已设置网格 {mesh_tag} 尺寸"}
        except Exception as e:
            logger.warning("mesh_set_size 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def mesh_stats(self, model_path: str, mesh_tag: str = "mesh1") -> Dict[str, Any]:
        """返回网格统计（单元数、顶点数等）。"""
        try:
            model = self._load_model(model_path)
            mesh_list = self._mesh_api(model)
            if not self._mesh_has(mesh_list, mesh_tag):
                return {"status": "error", "message": f"网格不存在: {mesh_tag}"}
            mesh = mesh_list(mesh_tag) if callable(mesh_list) else mesh_list.get(mesh_tag)
            out = {"status": "success", "num_vertex": None, "num_elem": None}
            if hasattr(mesh, "getNumVertex"):
                try:
                    out["num_vertex"] = mesh.getNumVertex()
                except Exception:
                    pass
            if hasattr(mesh, "getNumElem"):
                try:
                    out["num_elem"] = mesh.getNumElem()
                except Exception:
                    pass
            if hasattr(mesh, "stat"):
                try:
                    st = mesh.stat()
                    if st is not None:
                        if hasattr(st, "getNumVertex"):
                            out["num_vertex"] = st.getNumVertex()
                        if hasattr(st, "getNumElem"):
                            out["num_elem"] = st.getNumElem()
                except Exception:
                    pass
            return out
        except Exception as e:
            logger.warning("mesh_stats 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== 研究/求解高级 =====

    def clear_solution_data(
        self, model_path: str, solver_tag: Optional[str] = None
    ) -> Dict[str, Any]:
        """清除求解器序列关联的解数据。API: model.sol(solver_tag).clearSolutionData() 或类似。"""
        try:
            model = self._load_model(model_path)
            if not hasattr(model, "sol"):
                return {"status": "error", "message": "当前 COMSOL 模型无 sol() 接口"}
            sol_list = model.sol()
            tags = self._tags_or_names(sol_list)
            if solver_tag and solver_tag not in tags:
                return {"status": "error", "message": f"求解器序列不存在: {solver_tag}"}
            to_clear = [solver_tag] if solver_tag else tags
            for tag in to_clear:
                try:
                    seq = model.sol(tag) if callable(model.sol()) else sol_list.get(tag)
                    if seq is not None and hasattr(seq, "clearSolutionData"):
                        seq.clearSolutionData()
                except Exception as e:
                    logger.warning("clearSolutionData %s 失败: %s", tag, e)
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": "已清除求解数据"}
        except Exception as e:
            logger.warning("clear_solution_data 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== 结果/后处理与导出 =====

    def export_plot_image(
        self,
        model_path: str,
        plot_group_tag: str,
        out_path: str,
        width: int = 800,
        height: int = 600,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """导出结果图为图片。使用 result 下 export 或 plot 的 image 导出。"""
        try:
            model = self._load_model(model_path)
            if not hasattr(model, "result"):
                return {"status": "error", "message": "当前 COMSOL 模型无 result() 接口"}
            res = model.result()
            if not hasattr(res, "export"):
                return {"status": "error", "message": "result().export() 不可用"}
            exp_list = res.export()
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tag = "img1"
            try:
                exp_list.create(tag, "Image")
            except Exception:
                try:
                    exp_list.create(tag, "Plot")
                except Exception as e1:
                    return {"status": "error", "message": f"无法创建 Image 导出: {e1}"}
            feat = exp_list(tag) if callable(exp_list) else exp_list.get(tag)
            if feat is not None:
                feat.set("filename", str(path.resolve()))
                feat.set("width", str(width))
                feat.set("height", str(height))
                if plot_group_tag:
                    try:
                        feat.set("plotgroup", plot_group_tag)
                    except Exception:
                        pass
                for k, v in kwargs.items():
                    try:
                        feat.set(k, v)
                    except Exception:
                        pass
                if hasattr(feat, "run"):
                    feat.run()
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已导出图片到 {out_path}", "path": out_path}
        except Exception as e:
            logger.warning("export_plot_image 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def export_data(
        self,
        model_path: str,
        dataset_or_plot_tag: str,
        out_path: str,
        export_type: str = "Data",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """导出数据（表格/数据文件）。result().export().create(tag, type) + set + run()。"""
        try:
            model = self._load_model(model_path)
            if not hasattr(model, "result"):
                return {"status": "error", "message": "当前 COMSOL 模型无 result() 接口"}
            res = model.result()
            if not hasattr(res, "export"):
                return {"status": "error", "message": "result().export() 不可用"}
            exp_list = res.export()
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tag = "data1"
            try:
                exp_list.create(tag, export_type or "Data")
            except Exception as e1:
                return {"status": "error", "message": f"无法创建 Data 导出: {e1}"}
            feat = exp_list(tag) if callable(exp_list) else exp_list.get(tag)
            if feat is not None:
                feat.set("filename", str(path.resolve()))
                feat.set("data", dataset_or_plot_tag)
                for k, v in kwargs.items():
                    try:
                        feat.set(k, v)
                    except Exception:
                        pass
                if hasattr(feat, "run"):
                    feat.run()
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已导出数据到 {out_path}", "path": out_path}
        except Exception as e:
            logger.warning("export_data 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def table_export(
        self, model_path: str, table_tag: str, out_path: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """导出表格到文件。"""
        try:
            model = self._load_model(model_path)
            if not hasattr(model, "result"):
                return {"status": "error", "message": "当前 COMSOL 模型无 result() 接口"}
            res = model.result()
            if not hasattr(res, "table"):
                return {"status": "error", "message": "result().table() 不可用"}
            tbl = res.table(table_tag) if callable(res.table()) else res.table().get(table_tag)
            if tbl is None:
                return {"status": "error", "message": f"表格不存在: {table_tag}"}
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(tbl, "saveFile"):
                tbl.saveFile(str(path.resolve()))
            else:
                return {"status": "error", "message": "当前 COMSOL 版本表格无 saveFile()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已导出表格到 {out_path}", "path": out_path}
        except Exception as e:
            logger.warning("table_export 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def _materials_api(self, model):
        """Return the material sequence, preferring the component scope."""
        try:
            if self._node_list_has(model.component(), "comp1") and hasattr(
                model.component("comp1"), "material"
            ):
                return model.component("comp1").material()
        except Exception:
            pass
        try:
            if hasattr(model, "materials"):
                return model.materials()
            if hasattr(model, "material"):
                return model.material()
        except Exception as e:
            raise RuntimeError(f"COMSOL material API unavailable: {e}") from e
        raise RuntimeError("Current COMSOL model object has no material API")

    def _material_feature(self, model, name: str):
        """Return a material feature, preferring the component scope."""
        try:
            if self._node_list_has(model.component(), "comp1"):
                return model.component("comp1").material(name)
        except Exception:
            pass
        try:
            if hasattr(model, "materials"):
                return model.materials(name)
            if hasattr(model, "material"):
                return model.material(name)
        except Exception as e:
            raise RuntimeError(f"Failed to get material feature {name!r}: {e}") from e
        raise RuntimeError("Current COMSOL model object has no material feature API")

    def _find_unused_material_name(self, model, base: str) -> str:
        """在模型中找一个未使用的材料名称，如 mat1 -> mat2, mat3 ..."""
        mat_seq = self._materials_api(model)
        existing = set(self._tags_or_names(mat_seq))
        if base not in existing:
            return base
        for i in range(1, 100):
            candidate = f"{base}{i}" if base[-1].isdigit() else f"{base}_{i}"
            if candidate not in existing:
                return candidate
        return f"{base}_new"

    def _find_unused_physics_name(self, model, base: str) -> str:
        """在模型中找一个未使用的物理场名称，如 ht0 -> ht1, solid0 -> solid1 ..."""
        ph_seq = self._physics_api(model)
        existing = set(self._tags_or_names(ph_seq))
        if base not in existing:
            return base
        # 若 base 以数字结尾（如 ht0、solid0），尝试递增：ht1, ht2...
        m = re.match(r"^(.+?)(\d+)$", base)
        if m:
            prefix, num = m.group(1), int(m.group(2))
            for i in range(num + 1, num + 100):
                candidate = f"{prefix}{i}"
                if candidate not in existing:
                    return candidate
        for i in range(1, 100):
            candidate = f"{base}_{i}"
            if candidate not in existing:
                return candidate
        return f"{base}_new"

    def _find_unused_coord_system_name(self, model, base: str) -> str:
        comp = self._component_api(model)
        seq = None
        if comp is not None and hasattr(comp, "coordSystem"):
            seq = comp.coordSystem()
        elif hasattr(model, "coordSystem"):
            seq = model.coordSystem()
        existing = set(self._tags_or_names(seq)) if seq is not None else set()
        if base not in existing:
            return base
        m = re.match(r"^(.+?)(\d+)$", base)
        if m:
            prefix, num = m.group(1), int(m.group(2))
            for i in range(num + 1, num + 100):
                candidate = f"{prefix}{i}"
                if candidate not in existing:
                    return candidate
        for i in range(1, 100):
            candidate = f"{base}_{i}"
            if candidate not in existing:
                return candidate
        return f"{base}_new"

    def _find_unused_study_name(self, model, base: str) -> str:
        """在模型中找一个未使用的研究名称，如 std1 -> std2 ..."""
        st = model.study()
        existing = set(self._tags_or_names(st))
        if base not in existing:
            return base
        m = re.match(r"^(.+?)(\d+)$", base)
        if m:
            prefix, num = m.group(1), int(m.group(2))
            for i in range(num + 1, num + 100):
                candidate = f"{prefix}{i}"
                if candidate not in existing:
                    return candidate
        for i in range(1, 100):
            candidate = f"{base}_{i}"
            if candidate not in existing:
                return candidate
        return f"{base}_new"

    def _find_unused_solver_name(self, model, base: str = "sol1") -> str:
        """在模型中找一个未使用的求解器序列名称，如 sol1 -> sol2。"""
        try:
            sol = model.sol()
            existing = set(self._tags_or_names(sol))
        except Exception:
            existing = set()
        if base not in existing:
            return base
        m = re.match(r"^(.+?)(\d+)$", base)
        if m:
            prefix, num = m.group(1), int(m.group(2))
            for i in range(num + 1, num + 100):
                candidate = f"{prefix}{i}"
                if candidate not in existing:
                    return candidate
        for i in range(1, 100):
            candidate = f"{base}_{i}"
            if candidate not in existing:
                return candidate
        return f"{base}_new"

    def _create_pml_coord_system(
        self,
        model,
        name: str,
        selection: Any,
        parameters: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        comp = self._component_api(model)
        owner = comp if comp is not None and hasattr(comp, "coordSystem") else model
        if owner is None or not hasattr(owner, "coordSystem"):
            return None
        if not isinstance(selection, list) or not selection:
            return None

        tag = self._find_unused_coord_system_name(model, name or "pml1")
        coord_seq = owner.coordSystem()
        try:
            coord_seq.create(tag, "PML")
        except Exception:
            coord_seq.create(tag, "geom1", "PML")
        coord = owner.coordSystem(tag)
        try:
            coord.selection().set(selection)
        except Exception:
            pass
        for key, value in (parameters or {}).items():
            if key in EMW_UNSUPPORTED_PARAMETER_KEYS:
                continue
            try:
                coord.set(key, _comsol_value(value))
            except Exception:
                pass
        return {
            "kind": "pml_coord_system",
            "name": tag,
            "selection": selection,
            "created_as": "coordSystem",
        }

    def generate_unique_physics_name(self, model_path: str, base: str = "ht") -> Dict[str, Any]:
        """自动生成唯一的物理场节点名称。API 供迭代修复或执行器调用。"""
        try:
            model = self._load_model(model_path)
            name = self._find_unused_physics_name(model, base)
            return {"status": "success", "name": name, "base": base}
        except Exception as e:
            logger.warning("generate_unique_physics_name 失败: %s", e)
            return {"status": "error", "message": str(e), "name": base}

    def generate_unique_study_name(self, model_path: str, base: str = "std") -> Dict[str, Any]:
        """自动生成唯一的研究节点名称。API 供迭代修复或执行器调用。"""
        try:
            model = self._load_model(model_path)
            name = self._find_unused_study_name(model, base)
            return {"status": "success", "name": name, "base": base}
        except Exception as e:
            logger.warning("generate_unique_study_name 失败: %s", e)
            return {"status": "error", "message": str(e), "name": base}

    def add_materials(
        self,
        model_path: str,
        material_plan: MaterialPlan,
        run_single_file: bool = False,
        save_to_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """添加材料到模型。save_to_path 指定时保存到该新路径（避免占用）；未指定时自动生成新路径，避免覆盖原文件导致占用。"""
        logger.info("添加材料...")
        try:
            model = self._load_model(model_path)
            result = self._add_materials_direct(model, material_plan)
            if save_to_path and str(save_to_path).strip():
                saved_path = _save_model_to_new_path(model, Path(save_to_path))
            else:
                # 始终保存到新路径，避免同一进程内覆盖 model_path 导致「模型文件被占用」
                p = Path(model_path).resolve()
                default_save = p.parent / f"{p.stem}_material.mph"
                saved_path = _save_model_to_new_path(model, default_save)
            out = {"status": "success", "message": "材料设置成功", "result": result}
            out["saved_path"] = str(saved_path.resolve())
            return out
        except Exception as e:
            logger.error(f"添加材料失败: {e}")
            return {"status": "error", "message": str(e)}

    def _add_materials_direct(self, model, material_plan: MaterialPlan) -> Dict[str, Any]:
        mat_seq = self._materials_api(model)
        added = []
        name_map = {}  # 请求名 -> 实际使用名（智能创建时可能不同）
        for mat_def in material_plan.materials:
            actual_name = self._find_unused_material_name(model, mat_def.name)
            name_map[mat_def.name] = actual_name
            mat_seq.create(actual_name)
            feat = self._material_feature(model, actual_name)
            if mat_def.label:
                try:
                    feat.label(mat_def.label)
                except Exception:
                    pass

            if mat_def.builtin_name:
                try:
                    feat.materialType("lib")
                    feat.set("family", mat_def.builtin_name)
                except Exception:
                    logger.warning("内置材料加载失败: %s，将使用自定义属性", mat_def.builtin_name)
                    _ensure_material_thermal_k(feat, mat_def)
                _ensure_material_heat_properties(feat, mat_def)
                # 内置库偶发缺 E/nu 或加载失败时，显式补齐，保证固体力学可解
                _ensure_material_elastic_properties(feat, mat_def)
            else:
                group = mat_def.property_group or "def"
                prop_group = _material_property_group(feat, group)
                prop_names_lower = [p.name.strip().lower() for p in mat_def.properties]
                has_k = any(
                    n in ("k", "thermalconductivity", "thermal conductivity")
                    for n in prop_names_lower
                )
                has_e = any(
                    n in ("e", "youngsmodulus", "young's modulus", "youngs modulus")
                    for n in prop_names_lower
                )
                has_nu = any(
                    n in ("nu", "poissonsratio", "poisson's ratio", "poissons ratio")
                    for n in prop_names_lower
                )
                for prop in mat_def.properties:
                    name_to_set = MATERIAL_PROPERTY_COMSOL_ALIAS.get(prop.name, prop.name)
                    value_to_set = _comsol_value(prop.value, prop.unit or None)
                    try:
                        prop_group.set(name_to_set, value_to_set)
                    except Exception:
                        try:
                            prop_group.set(prop.name, value_to_set)
                        except Exception as e2:
                            logger.warning(
                                f"设置材料属性 {prop.name}（或 {name_to_set}）失败: {e2}"
                            )
                if not has_k:
                    _ensure_material_thermal_k(feat, mat_def)
                _ensure_material_heat_properties(feat, mat_def)
                if not (has_e and has_nu):
                    _ensure_material_elastic_properties(feat, mat_def)
            added.append(
                {"material": actual_name, "label": mat_def.label, "requested_name": mat_def.name}
            )

        for assignment in material_plan.assignments:
            mat_name = name_map.get(assignment.material_name, assignment.material_name)
            try:
                feat = self._material_feature(model, mat_name)
                if assignment.assign_all:
                    feat.selection().all()
                elif assignment.domain_ids:
                    feat.selection().set(assignment.domain_ids)
            except Exception as e:
                logger.warning("材料分配失败 %s: %s", mat_name, e)

        return {"materials": added}

    # ===== Physics =====

    def add_physics(
        self,
        model_path: str,
        physics_plan: PhysicsPlan,
        run_single_file: bool = False,
        save_to_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info("添加物理场...")
        try:
            model = self._load_model(model_path)
            result = self._add_physics_direct(model, physics_plan)
            if save_to_path:
                saved_path = _save_model_to_new_path(model, Path(save_to_path))
            else:
                saved_path = _save_model_avoid_lock(
                    model, Path(model_path), allow_fallback=not run_single_file
                )
            failures = result.get("failures", []) if isinstance(result, dict) else []
            out = {"status": "success", "message": "物理场设置成功", "result": result}
            if failures:
                out["status"] = "warning"
                out["message"] = f"物理场已创建，但存在 {len(failures)} 个子操作失败"
            out["saved_path"] = str(saved_path.resolve())
            return out
        except Exception as e:
            logger.error(f"添加物理场失败: {e}")
            return {"status": "error", "message": str(e)}

    def _add_physics_direct(self, model, physics_plan: PhysicsPlan) -> Dict[str, Any]:
        self._ensure_geometry_built(model)
        geom_tag = "geom1"
        added = []
        failures = []
        notes = []
        for i, field in enumerate(physics_plan.fields):
            tag = PHYSICS_TYPE_TO_COMSOL_TAG.get(field.type, "HeatTransfer")
            base_name = self._physics_interface_name(field.type, i)
            name = self._find_unused_physics_name(model, base_name)
            ph_seq = self._physics_api(model)
            try:
                ph_seq.create(name, tag, geom_tag)
            except Exception as e:
                logger.warning("物理场 create 失败，尝试 fallback: %s", e)
                try:
                    if self._node_list_has(model.component(), "comp1"):
                        model.component("comp1").physics().create(name, tag, geom_tag)
                    else:
                        model.physics().create(name, tag, geom_tag)
                except Exception as e2:
                    failures.append(
                        {
                            "kind": "physics_interface",
                            "name": name,
                            "field_type": field.type,
                            "error": str(e2),
                        }
                    )
                    logger.warning("物理场 fallback create 失败 %s: %s", name, e2)
                    continue

            ph_feat = self._physics_feature(model, name)
            if field.type == "heat":
                try:
                    model.param().set("k", "237[W/(m*K)]")
                    model.param().set("rho", "2700[kg/m^3]")
                    model.param().set("Cp", "900[J/(kg*K)]")
                except Exception as e:
                    logger.warning("璁剧疆榛樿鐑潗鏂欏弬鏁板け璐? %s", e)
                try:
                    solid = ph_feat.feature("solid1")
                    for key, value in {
                        "k_mat": "userdef",
                        "k": "237[W/(m*K)]",
                        "rho_mat": "userdef",
                        "rho": "2700[kg/m^3]",
                        "Cp_mat": "userdef",
                        "Cp": "900[J/(kg*K)]",
                    }.items():
                        try:
                            solid.set(key, value)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("璁剧疆 HeatTransfer solid1 榛樿鐑睘鎬уけ璐? %s", e)
            # Boundary conditions
            # 传热：先挂对流/温度（全外表面），再挂热通量，避免「all」覆盖底面热源
            boundary_conditions = list(field.boundary_conditions or [])
            if field.type == "heat":

                def _heat_bc_priority(bc_item) -> int:
                    ct = str(getattr(bc_item, "condition_type", "") or "")
                    if ct in {"HeatFlux", "heat_flux"}:
                        return 2
                    if _is_convective_heat_flux(ct) or ct in {
                        "Temperature",
                        "temperature",
                    }:
                        return 0
                    return 1

                boundary_conditions.sort(key=_heat_bc_priority)

            for bc in boundary_conditions:
                try:
                    if field.type == "heat":
                        feature_types = [_heat_boundary_feature_type(bc.condition_type)]
                    elif field.type == "electromagnetic":
                        if bc.condition_type in EMW_INTERFACE_CONTINUITY_TYPES:
                            notes.append(
                                {
                                    "kind": "skipped_boundary_condition",
                                    "interface": name,
                                    "name": bc.name,
                                    "condition_type": bc.condition_type,
                                    "reason": "dielectric_interfaces_use_default_emw_continuity",
                                }
                            )
                            continue
                        if bc.condition_type in EMW_PML_CONDITION_TYPES:
                            pml_note = self._create_pml_coord_system(
                                model, bc.name, bc.selection, bc.parameters
                            )
                            if pml_note:
                                pml_note["interface"] = name
                                notes.append(pml_note)
                                continue
                            notes.append(
                                {
                                    "kind": "boundary_condition_fallback",
                                    "interface": name,
                                    "name": bc.name,
                                    "requested_condition_type": bc.condition_type,
                                    "used_condition_type": "Scattering",
                                    "reason": "pml_requires_domain_selection_or_coord_system_api",
                                }
                            )
                            feature_types = ["Scattering", "ScatteringBoundaryCondition"]
                        else:
                            feature_types = _emw_boundary_feature_candidates(
                                bc.condition_type
                            )
                    else:
                        feature_types = [bc.condition_type]
                    feature_type = _physics_create_feature_with_candidates(
                        ph_feat, bc.name, feature_types
                    )
                    bc_feat = ph_feat.feature(bc.name)
                    _apply_physics_feature_selection(bc_feat, bc.selection)
                    if field.type == "heat":
                        _configure_heat_flux_boundary(
                            bc_feat, bc.condition_type, bc.parameters or {}
                        )
                    _set_feature_parameters_best_effort(
                        bc_feat,
                        bc.condition_type,
                        bc.parameters,
                        notes,
                        scope="boundary_condition",
                        feature_name=bc.name,
                    )
                    if feature_type != bc.condition_type:
                        notes.append(
                            {
                                "kind": "feature_type_alias",
                                "interface": name,
                                "name": bc.name,
                                "requested_condition_type": bc.condition_type,
                                "used_condition_type": feature_type,
                            }
                        )
                except Exception as e:
                    failures.append(
                        {
                            "kind": "boundary_condition",
                            "interface": name,
                            "name": bc.name,
                            "error": str(e),
                        }
                    )
                    logger.warning(f"设置边界条件 {bc.name} 失败: {e}")

            # Domain conditions
            for dc in field.domain_conditions:
                try:
                    ph_feat.create(dc.name, dc.condition_type)
                    if isinstance(dc.selection, list) and dc.selection:
                        ph_feat.feature(dc.name).selection().set(dc.selection)
                    _set_feature_parameters_best_effort(
                        ph_feat.feature(dc.name),
                        dc.condition_type,
                        dc.parameters,
                        notes,
                        scope="domain_condition",
                        feature_name=dc.name,
                    )
                except Exception as e:
                    failures.append(
                        {
                            "kind": "domain_condition",
                            "interface": name,
                            "name": dc.name,
                            "error": str(e),
                        }
                    )
                    logger.warning(f"设置域条件 {dc.name} 失败: {e}")

            # Initial conditions
            for ic in field.initial_conditions:
                try:
                    ph_feat.feature("init1").set(ic.variable, ic.value)
                except Exception:
                    try:
                        ph_feat.create(ic.name, "init")
                        ph_feat.feature(ic.name).set(ic.variable, ic.value)
                    except Exception as e:
                        failures.append(
                            {
                                "kind": "initial_condition",
                                "interface": name,
                                "name": ic.name,
                                "error": str(e),
                            }
                        )
                        logger.warning("设置初始条件 %s 失败: %s", ic.name, e)

            added.append({"interface": name, "type": field.type, "tag": tag})

        # Multi-physics couplings
        for coupling in physics_plan.couplings:
            ctag = COUPLING_TYPE_TO_COMSOL_TAG.get(coupling.type, coupling.type)
            try:
                model.multiphysics().create(coupling.type, ctag)
            except Exception as e:
                failures.append(
                    {
                        "kind": "coupling",
                        "name": coupling.type,
                        "tag": ctag,
                        "error": str(e),
                    }
                )
                logger.warning("创建耦合 %s 失败: %s", coupling.type, e)

        return {"interfaces": added, "failures": failures, "notes": notes}

    @staticmethod
    def _physics_interface_name(physics_type: str, index: int) -> str:
        prefix_map = {
            "heat": "ht",
            "electromagnetic": "emw",
            "structural": "solid",
            "fluid": "fluid",
            "acoustics": "acpr",
            "piezoelectric": "pzd",
            "chemical": "chds",
            "multibody": "mbd",
        }
        return f"{prefix_map.get(physics_type, physics_type[:3])}{index}"

    def _ensure_geometry_built(self, model) -> None:
        err_msgs = []
        try:
            if self._node_list_has(model.component(), "comp1") and self._node_list_has(model.component("comp1").geom(), "geom1"):
                model.component("comp1").geom("geom1").run()
                return
        except Exception as e:
            err_msgs.append(f"component.geom run 失败: {e}")
        try:
            if self._node_list_has(model.geom(), "geom1"):
                model.geom("geom1").run()
                return
        except Exception as e:
            err_msgs.append(f"root.geom run 失败: {e}")
        if err_msgs:
            raise RuntimeError("几何构建失败；".join(err_msgs))

    # ===== Mesh =====

    def generate_mesh(
        self,
        model_path: str,
        mesh_params: Dict[str, Any],
        run_single_file: bool = False,
        save_to_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info("生成网格...")
        try:
            model = self._load_model(model_path)
            self._generate_mesh_direct(model, mesh_params or {})
            if save_to_path:
                saved_path = _save_model_to_new_path(model, Path(save_to_path))
            else:
                saved_path = _save_model_avoid_lock(
                    model, Path(model_path), allow_fallback=not run_single_file
                )
            out = {"status": "success", "message": "网格划分成功", "result": {}}
            out["saved_path"] = str(saved_path.resolve())
            return out
        except Exception as e:
            logger.error(f"生成网格失败: {e}")
            return {"status": "error", "message": str(e)}

    def _mesh_has(self, mesh_list, tag: str) -> bool:
        if hasattr(mesh_list, "has"):
            return mesh_list.has(tag)
        if hasattr(mesh_list, "hasTag"):
            return mesh_list.hasTag(tag)
        return False

    def _generate_mesh_direct(self, model, mesh_params: Dict[str, Any]) -> None:
        mesh_name = "mesh1"
        geom_tag = "geom1"
        hauto = mesh_params.get("hauto", 5) if isinstance(mesh_params, dict) else 5
        try:
            if self._node_list_has(model.component(), "comp1"):
                mesh_seq = model.component("comp1").mesh()
                if not self._mesh_has(mesh_seq, mesh_name):
                    try:
                        mesh_seq.create(mesh_name, geom_tag)
                    except Exception:
                        mesh_seq.create(mesh_name)
                try:
                    model.component("comp1").mesh(mesh_name).create("size", "Size")
                except Exception:
                    pass
                try:
                    model.component("comp1").mesh(mesh_name).feature("size").set("hauto", hauto)
                except Exception:
                    pass
                model.component("comp1").mesh(mesh_name).run()
                return
        except Exception:
            pass
        ml = model.mesh()
        if not self._mesh_has(ml, mesh_name):
            ml.create(mesh_name, geom_tag)
        try:
            model.mesh(mesh_name).create("size", "Size")
        except Exception:
            pass
        try:
            model.mesh(mesh_name).feature("size").set("hauto", hauto)
        except Exception:
            pass
        model.mesh().run()

    # ===== Study =====

    def configure_study(
        self,
        model_path: str,
        study_plan: StudyPlan,
        run_single_file: bool = False,
        save_to_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info("配置研究...")
        try:
            model = self._load_model(model_path)
            result = self._configure_study_direct(model, study_plan)
            if save_to_path:
                saved_path = _save_model_to_new_path(model, Path(save_to_path))
            else:
                saved_path = _save_model_avoid_lock(
                    model, Path(model_path), allow_fallback=not run_single_file
                )
            failures = result.get("failures", []) if isinstance(result, dict) else []
            out = {"status": "success", "message": "研究配置成功", "result": result}
            if failures:
                out["status"] = "warning"
                out["message"] = f"研究已创建，但存在 {len(failures)} 个子操作失败"
            out["saved_path"] = str(saved_path.resolve())
            return out
        except Exception as e:
            logger.error(f"配置研究失败: {e}")
            return {"status": "error", "message": str(e)}

    def _configure_study_direct(self, model, study_plan: StudyPlan) -> Dict[str, Any]:
        added = []
        failures = []
        for i, st in enumerate(study_plan.studies):
            step_type = STUDY_TYPE_TO_COMSOL_TAG.get(st.type, "Stationary")
            base_name = f"std{i + 1}"
            name = self._find_unused_study_name(model, base_name)
            model.study().create(name)
            model.study(name).create("std", step_type)
            try:
                model.study(name).feature("std").set("rtol", "0.05")
            except Exception:
                pass

            if st.parametric_sweep:
                ps = st.parametric_sweep
                try:
                    model.study(name).create("param", "Parametric")
                    model.study(name).feature("param").set("pname", ps.parameter_name)
                    model.study(name).feature("param").set(
                        "prange", f"range({ps.range_start},{ps.step or ''},{ps.range_end})"
                    )
                except Exception as e:
                    failures.append(
                        {
                            "kind": "parametric_sweep",
                            "study": name,
                            "error": str(e),
                        }
                    )
                    logger.warning("参数化扫描配置失败: %s", e)

            added.append({"study": name, "type": st.type, "tag": step_type})
        return {"studies": added, "failures": failures}

    # ===== Solve =====

    def solve(
        self,
        model_path: str,
        run_single_file: bool = False,
        save_to_path: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        logger.info("执行求解...")
        progress_path: Optional[Path] = None
        stop_flag = threading.Event()
        poller: Optional[threading.Thread] = None
        try:
            model = self._load_model(model_path)
            backend = detect_compute_backend()
            if progress_callback:
                try:
                    progress_callback(
                        {
                            "phase": "prepare",
                            "percent": 1,
                            "message": "准备求解…",
                            "active": True,
                            "compute": backend.to_dict(),
                        }
                    )
                except Exception:
                    pass

            progress_path = self._enable_solve_progress_log()
            if progress_path is not None and progress_callback is not None:
                poller = threading.Thread(
                    target=self._poll_solve_progress_file,
                    args=(progress_path, progress_callback, stop_flag),
                    name="comsol-solve-progress",
                    daemon=True,
                )
                poller.start()

            study_name, gpu_active = self._solve_direct(
                model, progress_callback=progress_callback
            )
            compute = mark_solve_backend(
                gpu_active=gpu_active,
                applicable=gpu_active,
                reason=(
                    "本次求解已启用 COMSOL HardwareAcceleration（GPU）。"
                    if gpu_active
                    else ""
                ),
            )
            if save_to_path:
                saved_path = _save_model_to_new_path(model, Path(save_to_path))
            else:
                saved_path = _save_model_avoid_lock(
                    model, Path(model_path), allow_fallback=not run_single_file
                )
            out = {
                "status": "success",
                "message": "求解成功",
                "result": {"study": study_name, "gpu_active": gpu_active},
                "compute_backend": compute.to_dict(),
            }
            out["saved_path"] = str(saved_path.resolve())
            if progress_callback:
                try:
                    progress_callback(
                        {
                            "phase": "done",
                            "percent": 100,
                            "message": "求解完成",
                            "active": False,
                            "compute": compute.to_dict(),
                        }
                    )
                except Exception:
                    pass
            return out
        except Exception as e:
            logger.error(f"求解失败: {e}")
            compute = mark_solve_backend(gpu_active=False, reason=str(e)[:180])
            if progress_callback:
                try:
                    progress_callback(
                        {
                            "phase": "error",
                            "percent": 0,
                            "message": f"求解失败: {e}",
                            "active": False,
                            "compute": compute.to_dict(),
                        }
                    )
                except Exception:
                    pass
            return {
                "status": "error",
                "message": str(e),
                "compute_backend": compute.to_dict(),
            }
        finally:
            stop_flag.set()
            if poller is not None and poller.is_alive():
                poller.join(timeout=1.5)
            if progress_path is not None:
                try:
                    progress_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _enable_solve_progress_log(self) -> Optional[Path]:
        """启用 ModelUtil.showProgress(file)，便于轮询求解进度。"""
        try:
            jpype = _jpype()
            ModelUtil = jpype.JClass("com.comsol.model.util.ModelUtil")
            progress_path = Path(tempfile.gettempdir()) / f"mph-agent-solve-{uuid4().hex}.log"
            progress_path.write_text("", encoding="utf-8")
            ModelUtil.showProgress(str(progress_path))
            logger.info("已启用 COMSOL 进度日志: %s", progress_path)
            return progress_path
        except Exception as exc:
            logger.debug("启用 showProgress 失败（将仅上报阶段进度）: %s", exc)
            return None

    @staticmethod
    def _parse_progress_text(text: str) -> tuple[Optional[float], str]:
        """从进度日志文本中提取百分比与最近一行消息。"""
        if not text or not text.strip():
            return None, ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        message = lines[-1][:240] if lines else ""
        percent: Optional[float] = None
        # 优先匹配显式百分号
        for ln in reversed(lines):
            m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", ln)
            if m:
                percent = max(0.0, min(100.0, float(m.group(1))))
                message = ln[:240]
                break
        if percent is None:
            for ln in reversed(lines):
                m = re.search(r"(?:progress|进度)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)", ln, re.I)
                if m:
                    percent = max(0.0, min(100.0, float(m.group(1))))
                    message = ln[:240]
                    break
        return percent, message

    def _poll_solve_progress_file(
        self,
        progress_path: Path,
        callback: Callable[[Dict[str, Any]], None],
        stop_flag: threading.Event,
    ) -> None:
        last_payload = ""
        while not stop_flag.is_set():
            try:
                if progress_path.exists():
                    text = progress_path.read_text(encoding="utf-8", errors="ignore")
                    percent, message = self._parse_progress_text(text)
                    if message or percent is not None:
                        payload = {
                            "phase": "solving",
                            "percent": percent if percent is not None else 0,
                            "message": message or "求解中…",
                            "active": True,
                        }
                        key = f"{payload['percent']}|{payload['message']}"
                        if key != last_payload:
                            last_payload = key
                            callback(payload)
            except Exception:
                pass
            stop_flag.wait(0.4)

    def _try_enable_gpu_acceleration(self, model, study_name: str) -> bool:
        """对时间求解器尝试挂载 HardwareAcceleration（仅部分声学等场景有效）。"""
        if not should_attempt_gpu():
            logger.info("按计算偏好跳过 GPU HardwareAcceleration")
            return False
        backend = detect_compute_backend()
        if not backend.gpu_available:
            return False
        try:
            sol_tags = list(model.sol().tags()) if hasattr(model, "sol") else []
        except Exception:
            sol_tags = []
        enabled = False
        for sol_tag in sol_tags:
            try:
                sol = model.sol(sol_tag)
                feat_tags = list(sol.feature().tags())
            except Exception:
                continue
            for feat_tag in feat_tags:
                try:
                    feat = sol.feature(feat_tag)
                    # Time / TimeExplicit 类特征才有意义
                    ftype = ""
                    try:
                        ftype = str(feat.getType())
                    except Exception:
                        ftype = str(feat_tag)
                    if "time" not in ftype.lower() and "time" not in str(feat_tag).lower():
                        continue
                    # 已有则直接打开；没有则创建
                    child_tags = []
                    try:
                        child_tags = [str(t) for t in feat.feature().tags()]
                    except Exception:
                        child_tags = []
                    ha_tag = next(
                        (t for t in child_tags if "hardware" in t.lower() or t.lower() == "ha1"),
                        None,
                    )
                    if ha_tag is None:
                        try:
                            feat.create("ha1", "HardwareAcceleration")
                            ha_tag = "ha1"
                        except Exception:
                            continue
                    ha = feat.feature(ha_tag)
                    for key, val in (
                        ("dgacc", True),
                        ("gpuresidual", True),
                        ("gpusingleprecision", False),
                    ):
                        try:
                            ha.set(key, val)
                        except Exception:
                            pass
                    enabled = True
                    logger.info(
                        "已为求解器 %s/%s 启用 HardwareAcceleration", sol_tag, feat_tag
                    )
                except Exception as exc:
                    logger.debug("启用 GPU 加速失败 %s/%s: %s", sol_tag, feat_tag, exc)
        if not enabled:
            # 研究步本身为 Time 时也记一笔，便于前端说明
            try:
                st = model.study(study_name)
                for t in st.feature().tags():
                    try:
                        if "time" in str(st.feature(t).getType()).lower():
                            logger.info(
                                "研究含时间步，但未能挂载 HardwareAcceleration（可能物理场不支持）"
                            )
                            break
                    except Exception:
                        pass
            except Exception:
                pass
        return enabled

    def _solve_direct(
        self,
        model,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> tuple[str, bool]:
        tags = model.study().tags()
        if not tags:
            raise RuntimeError("模型中没有研究，请先配置研究")
        study_name = tags[-1]
        gpu_active = False
        try:
            gpu_active = bool(self._try_enable_gpu_acceleration(model, study_name))
        except Exception as exc:
            logger.debug("尝试 GPU 加速时异常: %s", exc)
        if progress_callback:
            try:
                progress_callback(
                    {
                        "phase": "solving",
                        "percent": 5,
                        "message": (
                            "GPU 加速求解中…" if gpu_active else "CPU 多核求解中…"
                        ),
                        "active": True,
                    }
                )
            except Exception:
                pass
        try:
            model.study(study_name).run()
        except Exception as first_error:
            logger.warning("默认 study.run() 求解失败，尝试直接求解器 fallback: %s", first_error)
            self._run_stationary_direct_solver(model, study_name)
            gpu_active = False
        return study_name, gpu_active

    def _run_stationary_direct_solver(self, model, study_name: str) -> str:
        """Create a conservative stationary solver sequence with PARDISO."""
        sol_name = self._find_unused_solver_name(model, "sol1")
        model.sol().create(sol_name)
        sol = model.sol(sol_name)
        try:
            sol.study(study_name)
        except Exception:
            pass
        try:
            sol.attach(study_name)
        except Exception:
            pass

        sol.create("st1", "StudyStep")
        try:
            sol.feature("st1").set("study", study_name)
            sol.feature("st1").set("studystep", "std")
        except Exception:
            pass

        sol.create("v1", "Variables")
        sol.create("s1", "Stationary")
        try:
            sol.feature("s1").feature().remove("fcDef")
        except Exception:
            pass
        try:
            sol.feature("s1").create("fc1", "FullyCoupled")
        except Exception:
            pass
        try:
            sol.feature("s1").create("d1", "Direct")
            sol.feature("s1").feature("d1").set("linsolver", "pardiso")
        except Exception:
            pass
        try:
            sol.feature("s1").set("stol", "0.05")
        except Exception:
            pass
        sol.runAll()
        return sol_name

    # ===== Direct operations =====

    def execute_direct(
        self, operation: str, model_path: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.debug(f"直接调用 Java API: {operation}")
        try:
            model = self._load_model(model_path)
            if operation == "set_parameter":
                result = self._set_parameter_direct(model, parameters)
            elif operation == "add_boundary_condition":
                result = self._add_boundary_condition_direct(model, parameters)
            else:
                raise ValueError(f"不支持的直接操作: {operation}")
            model.save(model_path)
            return {"status": "success", "message": f"直接执行 {operation} 成功", "result": result}
        except Exception as e:
            logger.error(f"直接调用 Java API 失败: {e}")
            return {"status": "error", "message": f"直接调用失败: {e}"}

    def validate_execution(
        self, model_path: str, expected_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            path = Path(model_path)
            if not path.exists():
                return {"status": "error", "message": "模型文件不存在"}

            if path.stat().st_size == 0:
                return {"status": "error", "message": "模型文件为空"}

            expected = expected_result or {}
            tree_info = self.list_model_tree(model_path)
            if tree_info.get("status") == "error":
                return {
                    "status": "warning",
                    "message": f"模型文件存在，但树验证失败: {tree_info.get('message', '未知错误')}",
                }

            tree = tree_info.get("tree", {})
            if expected.get("require_physics") and not tree.get("physics"):
                return {"status": "error", "message": "验证失败：未检测到物理场节点"}
            if expected.get("require_study") and not tree.get("studies"):
                return {"status": "error", "message": "验证失败：未检测到研究节点"}
            if expected.get("require_mesh") and not tree.get("meshes"):
                return {"status": "error", "message": "验证失败：未检测到网格节点"}

            return {"status": "success", "message": "验证通过", "tree": tree}
        except Exception as e:
            return {"status": "error", "message": f"验证失败: {e}"}

    def fetch_official_api_entries(
        self, url: str = OFFICIAL_COMSOL_API_INDEX_URL, refresh: bool = False
    ) -> List[Dict[str, str]]:
        if self._official_api_entries is not None and not refresh:
            return self._official_api_entries
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=60) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        html_pattern = re.compile(
            r">([A-Za-z_]\w*\([^<)]*\))</a></span>\s*-\s*Method in (?:interface|class)\s*([^<]*?)<a[^>]*>\s*([A-Za-z_]\w*)\s*</a>",
            re.IGNORECASE,
        )
        found = []
        for signature, owner_prefix, owner_tail in html_pattern.findall(html):
            owner = re.sub(r"\s+", "", unescape(owner_prefix)) + owner_tail
            found.append((signature, owner))
        if not found:
            text = unescape(re.sub(r"<[^>]+>", " ", html))
            text = re.sub(r"\s+", " ", text)
            pattern = re.compile(
                r"([A-Za-z_]\w*\([^)]*\))\s*-\s*Method in (?:interface|class)\s+([A-Za-z_][\w.]*)",
                re.IGNORECASE,
            )
            found = pattern.findall(text)
        unique: Dict[str, Dict[str, str]] = {}
        for signature, owner in found:
            method_name = signature.split("(", 1)[0]
            key = f"{owner}::{signature}"
            if key not in unique:
                unique[key] = {"owner": owner, "signature": signature, "method_name": method_name}
        self._official_api_entries = list(unique.values())
        return self._official_api_entries

    def _build_wrapper_name(self, owner: str, method_name: str, used: Dict[str, int]) -> str:
        owner_tail = owner.split(".")[-1]
        owner_token = re.sub(r"[^A-Za-z0-9_]", "_", owner_tail).lower()
        method_token = re.sub(r"[^A-Za-z0-9_]", "_", method_name).lower()
        base = f"api_{owner_token}_{method_token}"
        used[base] = used.get(base, 0) + 1
        if used[base] == 1:
            return base
        return f"{base}_{used[base]}"

    def _resolve_api_target(self, model, target_path: Any):
        if target_path is None:
            return model
        target = model
        if isinstance(target_path, list):
            for step in target_path:
                if not isinstance(step, dict):
                    raise ValueError("target_path 列表项必须为对象")
                method_name = step.get("method")
                if not isinstance(method_name, str) or not method_name.strip():
                    raise ValueError("target_path 列表项的 method 必须为非空字符串")
                args = step.get("args", [])
                if not isinstance(args, list):
                    raise ValueError("target_path 的 args 必须为列表")
                target = self._get_comsol_runner().invoke_java_method(target, method_name, *args)
            return target
        if isinstance(target_path, str):
            token_pattern = re.compile(r"([A-Za-z_]\w*)\(([^)]*)\)|([A-Za-z_]\w*)")
            for match in token_pattern.finditer(target_path):
                method_name = match.group(1) or match.group(3)
                if not method_name:
                    continue
                args_txt = match.group(2)
                args: List[Any] = []
                if args_txt:
                    parts = [p.strip() for p in args_txt.split(",") if p.strip()]
                    for p in parts:
                        raw = p.strip()
                        if (raw.startswith("'") and raw.endswith("'")) or (
                            raw.startswith('"') and raw.endswith('"')
                        ):
                            args.append(raw[1:-1])
                        else:
                            try:
                                args.append(int(raw))
                            except ValueError:
                                try:
                                    args.append(float(raw))
                                except ValueError:
                                    args.append(raw)
                target = self._get_comsol_runner().invoke_java_method(target, method_name, *args)
            return target
        raise ValueError("target_path 必须为字符串、步骤数组或空")

    def invoke_official_api(
        self,
        model_path: str,
        method_name: str,
        args: Optional[List[Any]] = None,
        target_path: Any = None,
    ) -> Dict[str, Any]:
        try:
            model = self._load_model(model_path)
            target = self._resolve_api_target(model, target_path)
            result = self._get_comsol_runner().invoke_java_method(target, method_name, *(args or []))
            saved_path = _save_model_avoid_lock(model, Path(model_path))
            out = {"status": "success", "method": method_name, "result": str(result)}
            if saved_path != Path(model_path):
                out["saved_path"] = str(saved_path)
            return out
        except Exception as e:
            logger.error("invoke_official_api 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def invoke_official_static_api(
        self, class_name: str, method_name: str, args: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        try:
            COMSOLRunner._ensure_jvm_started()
            result = self._get_comsol_runner().invoke_static_api(class_name, method_name, *(args or []))
            return {
                "status": "success",
                "class_name": class_name,
                "method": method_name,
                "result": str(result),
            }
        except Exception as e:
            logger.error("invoke_official_static_api 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def register_official_api_wrappers(
        self, url: str = OFFICIAL_COMSOL_API_INDEX_URL, refresh: bool = False
    ) -> Dict[str, Any]:
        entries = self.fetch_official_api_entries(url=url, refresh=refresh)
        if refresh:
            self._official_api_wrappers = {}
        used: Dict[str, int] = {}
        for entry in entries:
            method_name = entry["method_name"]
            owner = entry["owner"]
            wrapper_name = self._build_wrapper_name(owner, method_name, used)
            if wrapper_name in self._official_api_wrappers:
                continue

            def _wrapper(
                self,
                model_path: str,
                args: Optional[List[Any]] = None,
                target_path: Any = None,
                _method=method_name,
            ):
                return self.invoke_official_api(
                    model_path=model_path, method_name=_method, args=args, target_path=target_path
                )

            setattr(self, wrapper_name, MethodType(_wrapper, self))
            self._official_api_wrappers[wrapper_name] = entry
        return {
            "status": "success",
            "total_entries": len(entries),
            "total_wrappers": len(self._official_api_wrappers),
            "wrappers": list(self._official_api_wrappers.keys()),
        }

    def render_official_api_wrapper_module(
        self, url: str = OFFICIAL_COMSOL_API_INDEX_URL, refresh: bool = False
    ) -> str:
        entries = self.fetch_official_api_entries(url=url, refresh=refresh)
        used: Dict[str, int] = {}
        wrappers: List[Dict[str, str]] = []
        for entry in entries:
            method_name = entry["method_name"]
            owner = entry["owner"]
            wrapper_name = self._build_wrapper_name(owner, method_name, used)
            wrappers.append(
                {"wrapper_name": wrapper_name, "method_name": method_name, "owner": owner}
            )

        lines: List[str] = []
        lines.append('"""自动生成的 COMSOL 官方 API 包装函数集合。"""')
        lines.append("from typing import Any, List, Optional")
        lines.append("")
        lines.append("")
        lines.append("class OfficialComsolApiWrappersMixin:")
        lines.append("    _OFFICIAL_WRAPPER_META = {")
        for w in wrappers:
            lines.append(
                f'        "{w["wrapper_name"]}": {{"method": "{w["method_name"]}", "owner": "{w["owner"]}"}},'
            )
        lines.append("    }")
        lines.append("")
        for w in wrappers:
            lines.append(
                f"    def {w['wrapper_name']}(self, model_path: str, args: Optional[List[Any]] = None, target_path: Any = None):"
            )
            lines.append(
                f'        return self.invoke_official_api(model_path=model_path, method_name="{w["method_name"]}", args=args, target_path=target_path)'
            )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def write_official_api_wrapper_module(
        self,
        output_path: Optional[str] = None,
        url: str = OFFICIAL_COMSOL_API_INDEX_URL,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        if output_path is None:
            output_path = str(Path(__file__).resolve().parent / "comsol_official_api_wrappers.py")
        source = self.render_official_api_wrapper_module(url=url, refresh=refresh)
        out = Path(output_path).resolve()
        out.write_text(source, encoding="utf-8")
        wrapper_count = source.count("def api_")
        return {
            "status": "success",
            "path": str(out),
            "wrapper_count": wrapper_count,
        }

    def load_official_api_wrapper_module(self, module_path: Optional[str] = None) -> Dict[str, Any]:
        if module_path is None:
            module_path = str(Path(__file__).resolve().parent / "comsol_official_api_wrappers.py")
        path = Path(module_path).resolve()
        if not path.exists():
            return {"status": "error", "message": f"包装模块不存在: {path}"}
        spec = importlib.util.spec_from_file_location("comsol_official_api_wrappers", str(path))
        if spec is None or spec.loader is None:
            return {"status": "error", "message": "无法加载包装模块 spec"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        mixin_cls = getattr(module, "OfficialComsolApiWrappersMixin", None)
        if mixin_cls is None:
            return {"status": "error", "message": "包装模块缺少 OfficialComsolApiWrappersMixin"}
        loaded = []
        for name, value in mixin_cls.__dict__.items():
            if name.startswith("api_") and callable(value):
                setattr(self, name, MethodType(value, self))
                loaded.append(name)
        self._official_api_wrappers.update(getattr(mixin_cls, "_OFFICIAL_WRAPPER_META", {}))
        return {"status": "success", "loaded": len(loaded), "wrappers": loaded}

    # ===== Official API 能力表导出 =====

    def list_official_api_wrappers(
        self,
        query: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        返回已加载的 COMSOL 官方 API 包装函数列表，便于前端浏览与向量检索构建能力表。

        返回字段：
        - items: [{wrapper_name, owner, method_name}]
        - total: 总条数
        - limit/offset: 分页信息
        """
        meta = self._official_api_wrappers or {}
        records: List[Dict[str, str]] = []
        for wrapper_name, info in meta.items():
            owner = info.get("owner") or ""
            method_name = info.get("method") or info.get("method_name") or ""
            records.append(
                {
                    "wrapper_name": wrapper_name,
                    "owner": owner,
                    "method_name": method_name,
                }
            )
        # 简单文本过滤
        if query:
            q = query.lower()
            records = [
                r
                for r in records
                if q in r["wrapper_name"].lower()
                or q in r["owner"].lower()
                or q in r["method_name"].lower()
            ]
        total = len(records)
        records.sort(key=lambda r: r["wrapper_name"])
        if limit is not None and limit > 0:
            start = max(0, offset)
            end = start + limit
            records = records[start:end]
        return {
            "status": "success",
            "items": records,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # ===== 模型预览（导出几何/结果图为 PNG，供桌面端显示）=====

    def export_model_preview(
        self, model_path: str, width: int = 640, height: int = 480
    ) -> Dict[str, Any]:
        """加载 .mph 模型，导出几何或结果图为 PNG，返回 base64 编码供前端显示。"""
        path = Path(model_path)
        if not path.exists():
            return {"status": "error", "message": "模型文件不存在", "image_base64": None}
        try:
            model = self._load_model(model_path)
            fd, out_path = tempfile.mkstemp(suffix=".png", prefix="comsol_preview_")
            try:
                import os

                os.close(fd)
            except Exception:
                pass
            out_path = Path(out_path)
            try:
                geom = self._geom_for_export(model)
                if geom is not None:
                    img = geom.image()
                    img.set("pngfilename", str(out_path.resolve()))
                    img.set("width", str(width))
                    img.set("height", str(height))
                    img.export()
                else:
                    raise RuntimeError("无几何节点")
            except Exception as e1:
                logger.warning("几何导出失败: %s", e1)
                if out_path.exists():
                    out_path.unlink(missing_ok=True)
                return {"status": "error", "message": f"预览导出失败: {e1}", "image_base64": None}
            if not out_path.exists():
                return {"status": "error", "message": "未生成预览图", "image_base64": None}
            data = out_path.read_bytes()
            out_path.unlink(missing_ok=True)
            b64 = base64.b64encode(data).decode("ascii")
            return {"status": "success", "message": "预览已生成", "image_base64": b64}
        except Exception as e:
            logger.exception("export_model_preview 失败")
            return {"status": "error", "message": str(e), "image_base64": None}

    def _geom_for_export(self, model):
        """获取用于导出的几何对象。"""
        try:
            if self._node_list_has(model.component(), "comp1") and self._node_list_has(model.component("comp1").geom(), "geom1"):
                return model.component("comp1").geom("geom1")
        except Exception:
            pass
        try:
            if self._node_list_has(model.geom(), "geom1"):
                return model.geom("geom1")
        except Exception:
            pass
        return None

    def _set_parameter_direct(self, model, parameters: Dict[str, Any]) -> Dict[str, Any]:
        param_name = parameters.get("name")
        param_value = parameters.get("value")
        if not param_name or param_value is None:
            raise ValueError("参数名称和值必须提供")
        model.param().set(param_name, param_value)
        return {"parameter": param_name, "value": param_value}

    def _add_boundary_condition_direct(self, model, parameters: Dict[str, Any]) -> Dict[str, Any]:
        physics_name = parameters.get("physics_name", "ht")
        boundary_name = parameters.get("boundary_name", "bc1")
        condition_type = parameters.get("condition_type", "Temperature")
        ph_feat = self._physics_feature(model, physics_name)
        ph_feat.create(boundary_name, condition_type)
        for k, v in parameters.get("params", {}).items():
            ph_feat.feature(boundary_name).set(k, v)
        return {"physics": physics_name, "boundary": boundary_name, "type": condition_type}

    # ===== Globals / case extraction / ops catalog =====

    @staticmethod
    def _normalize_comsol_error(exc: Exception) -> str:
        msg = str(exc)
        low = msg.lower()
        if (
            "jpype" in low
            or "jvm" in low
            or "com.comsol" in low
            or "classnotfound" in low
            or "module named 'com'" in low
        ):
            return f"COMSOL/JVM environment unavailable: {msg}"
        return msg

    @staticmethod
    def _global_name_ok(name: str) -> bool:
        return bool(re.match(r"^[A-Za-z_]\w*$", name or ""))

    def define_global_parameters(
        self,
        model_path: str,
        definitions: List[Dict[str, Any]],
        save_to_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        path = Path(model_path).resolve()
        if not path.exists():
            return {"status": "error", "message": f"model file not found: {path}"}
        if not isinstance(definitions, list) or not definitions:
            return {"status": "error", "message": "global definitions are empty"}

        parsed: List[GlobalDefinitionPlan] = []
        seen: set[str] = set()
        errors: List[Dict[str, Any]] = []

        for idx, item in enumerate(definitions, start=1):
            try:
                definition = (
                    item
                    if isinstance(item, GlobalDefinitionPlan)
                    else GlobalDefinitionPlan.model_validate(item or {})
                )
            except Exception as e:
                errors.append(
                    {
                        "index": idx,
                        "field": "global_definitions",
                        "message": f"invalid schema: {e}",
                    }
                )
                continue

            name = (definition.name or "").strip()
            value = (definition.value or "").strip()
            if not name:
                errors.append({"index": idx, "field": "name", "message": "name is required"})
                continue
            if not self._global_name_ok(name):
                errors.append(
                    {
                        "index": idx,
                        "field": "name",
                        "message": "name must match [A-Za-z_]\\w*",
                    }
                )
                continue
            low = name.lower()
            if low in seen:
                errors.append({"index": idx, "field": "name", "message": f"duplicate name: {name}"})
                continue
            seen.add(low)
            if not value:
                errors.append({"index": idx, "field": "value", "message": f"value is required: {name}"})
                continue

            parsed.append(definition)

        if errors:
            return {
                "status": "error",
                "message": "global definitions validation failed",
                "details": errors,
            }

        try:
            model = self._load_model(str(path))
            param_api = model.param()
            if param_api is None or not hasattr(param_api, "set"):
                return {
                    "status": "error",
                    "message": "model.param() API is unavailable in current COMSOL version",
                }

            written: List[Dict[str, Any]] = []
            for definition in parsed:
                expression = (definition.value or "").strip()
                unit = (definition.unit or "").strip() if definition.unit else ""
                if unit and "[" not in expression:
                    expression = f"{expression}[{unit}]"
                if definition.description:
                    try:
                        # Some versions support set(name, expr, desc)
                        param_api.set(definition.name, expression, definition.description)
                    except Exception:
                        param_api.set(definition.name, expression)
                        try:
                            if hasattr(param_api, "descr"):
                                param_api.descr(definition.name, definition.description)
                        except Exception:
                            pass
                else:
                    param_api.set(definition.name, expression)

                written.append(
                    {
                        "name": definition.name,
                        "value": definition.value,
                        "unit": definition.unit,
                        "description": definition.description,
                    }
                )

            target = Path(save_to_path).resolve() if save_to_path else path
            if save_to_path:
                saved_path = _save_model_to_new_path(model, target)
            else:
                saved_path = _save_model_avoid_lock(model, target)

            return {
                "status": "success",
                "message": f"written {len(written)} global parameters",
                "count": len(written),
                "written": written,
                "saved_path": str(saved_path),
            }
        except Exception as e:
            msg = self._normalize_comsol_error(e)
            logger.exception("define_global_parameters failed")
            return {"status": "error", "message": msg}

    def list_global_parameters(self, model_path: str) -> Dict[str, Any]:
        path = Path(model_path).resolve()
        if not path.exists():
            return {"status": "error", "message": f"model file not found: {path}", "items": []}

        try:
            model = self._load_model(str(path))
            param_api = model.param()
            if param_api is None:
                return {
                    "status": "error",
                    "message": "model.param() API is unavailable in current COMSOL version",
                    "items": [],
                }

            names: List[str] = []
            for getter in ("varnames", "names", "tags"):
                if hasattr(param_api, getter):
                    try:
                        raw = getattr(param_api, getter)()
                        if raw is not None:
                            names = [str(x) for x in raw]
                            break
                    except Exception:
                        continue

            items: List[Dict[str, Any]] = []
            for name in names:
                value = ""
                description: Optional[str] = None

                for getter in ("get", "evaluate", "expr"):
                    if hasattr(param_api, getter):
                        try:
                            got = getattr(param_api, getter)(name)
                            if got is not None:
                                value = str(got)
                                break
                        except Exception:
                            continue

                if hasattr(param_api, "descr"):
                    try:
                        got_desc = param_api.descr(name)
                        if got_desc is not None:
                            description = str(got_desc)
                    except Exception:
                        pass

                unit = None
                m = re.search(r"\[([^\]]+)\]\s*$", value or "")
                if m:
                    unit = m.group(1)

                items.append(
                    {
                        "name": name,
                        "value": value,
                        "unit": unit,
                        "description": description,
                    }
                )

            return {"status": "success", "items": items, "total": len(items)}
        except Exception as e:
            msg = self._normalize_comsol_error(e)
            logger.exception("list_global_parameters failed")
            return {"status": "error", "message": msg, "items": []}

    @staticmethod
    def _infer_category(owner: str, method_name: str, label: str = "") -> str:
        """按 Java owner 类名粗分建模域；避免用子串 ``param`` 误判（如 ``SaveItemParam``）。"""
        o = (owner or "").lower()
        m = (method_name or "").lower()
        lab = (label or "").lower()
        text = f"{o} {m} {lab}"

        # 版本管理 / 数据库 API，与模型「参数定义」无关
        if "com.comsol.api." in o:
            return "开发工具"

        if any(
            x in o
            for x in (
                "geomsequence",
                "geometryfeature",
                "geomfeature",
                "geomobject",
                "geometryanalysis",
                "hidegeom",
                "sketch",
                "workplane",
                "cadimport",
                "partinstance",
            )
        ):
            return "几何"
        if any(x in o for x in ("meshsequence", "meshfeature", "meshmapping", "meshtool")):
            return "网格"
        if "material" in o:
            return "材料"
        if any(
            x in o
            for x in (
                "physics",
                "multiphysics",
                "heattransfer",
                "structuralmechanics",
                "acoustic",
                "chemical",
                "electromagnetic",
                "fluid",
            )
        ):
            return "物理场"
        if any(x in o for x in ("studyfeature", "solversequence", "solverfeature")):
            return "研究"
        if any(x in o for x in ("numericalfeature", "tablefeature", "dataset", "exporttag", "renderer")):
            return "结果"
        if "plot" in o or "plotgroup" in o:
            return "结果"

        # 几何域上的选择、嵌入选择等（须在泛化的 ``param`` 匹配之前）
        if any(
            x in o
            for x in (
                "embeddedselection",
                "geomobjectselection",
                "geomobjectgroupselection",
                "com.comsol.model.selection",
            )
        ):
            return "几何"
        if o.endswith(".selection") or ".selection." in o:
            return "几何"

        # 全局参数 / 参数组 / 单位制等
        if any(x in o for x in ("parametercontainer", "parameterentity", "parambase")):
            return "定义"
        if "unitsystem" in o or o.endswith(".unit") or ".units." in o:
            return "定义"
        if "functionfeature" in o or o.endswith(".function") or ".functions." in o:
            return "定义"

        # 回退：旧版基于全文关键词（不再用裸 ``param``，避免 ItemParam 等误判）
        if any(k in text for k in ["variable", "expression"]) and "itemparam" not in text:
            return "定义"
        if any(k in text for k in ["geom", "workplane", "cad", "sketch"]):
            return "几何"
        if "material" in text:
            return "材料"
        if any(k in text for k in ["physics", "multiphysics", "heattransfer", "electromagnetic"]):
            return "物理场"
        if "mesh" in text:
            return "网格"
        if any(k in text for k in ["study", "solver", "solution", "stationary"]):
            return "研究"
        if any(k in text for k in ["result", "plot", "table", "dataset", "export"]):
            return "结果"
        return "开发工具"

    @staticmethod
    def _catalog_categories() -> List[str]:
        return ["定义", "几何", "材料", "物理场", "网格", "研究", "结果", "开发工具"]

    def _native_ops_catalog_items(self) -> List[Dict[str, Any]]:
        return [
            {
                "category": "定义",
                "label": "全局参数定义",
                "invoke_mode": "native",
                "recommended_action": "define_globals",
                "params_schema": {"global_definitions": "GlobalDefinitionPlan[]", "save_to_path": "string?"},
                "examples": [{"action": "define_globals", "params": {"global_definitions": [{"name": "L", "value": "0.1[m]"}]}}],
            },
            {
                "category": "几何",
                "label": "创建几何",
                "invoke_mode": "native",
                "recommended_action": "create_geometry",
                "params_schema": {"geometry_plan": "GeometryPlan"},
                "examples": [{"action": "create_geometry"}],
            },
            {
                "category": "几何",
                "label": "导入几何",
                "invoke_mode": "native",
                "recommended_action": "import_geometry",
                "params_schema": {"file_path": "string", "geom_tag": "string?"},
                "examples": [{"action": "import_geometry", "params": {"file_path": "input.step"}}],
            },
            {
                "category": "几何",
                "label": "创建选择集",
                "invoke_mode": "native",
                "recommended_action": "create_selection",
                "params_schema": {"selection_tag": "string", "entities": "int[]"},
                "examples": [{"action": "create_selection"}],
            },
            {
                "category": "材料",
                "label": "添加材料",
                "invoke_mode": "native",
                "recommended_action": "add_material",
                "params_schema": {"material_plan": "MaterialPlan"},
                "examples": [{"action": "add_material"}],
            },
            {
                "category": "材料",
                "label": "更新材料属性",
                "invoke_mode": "native",
                "recommended_action": "update_material_property",
                "params_schema": {"material_name": "string", "properties": "object"},
                "examples": [{"action": "update_material_property"}],
            },
            {
                "category": "物理场",
                "label": "添加物理场",
                "invoke_mode": "native",
                "recommended_action": "add_physics",
                "params_schema": {"physics_plan": "PhysicsPlan"},
                "examples": [{"action": "add_physics"}],
            },
            {
                "category": "网格",
                "label": "生成网格",
                "invoke_mode": "native",
                "recommended_action": "generate_mesh",
                "params_schema": {"mesh_params": "object"},
                "examples": [{"action": "generate_mesh"}],
            },
            {
                "category": "研究",
                "label": "配置研究",
                "invoke_mode": "native",
                "recommended_action": "configure_study",
                "params_schema": {"study_plan": "StudyPlan"},
                "examples": [{"action": "configure_study"}],
            },
            {
                "category": "研究",
                "label": "求解",
                "invoke_mode": "native",
                "recommended_action": "solve",
                "params_schema": {"model_path": "string"},
                "examples": [{"action": "solve"}],
            },
            {
                "category": "结果",
                "label": "导出结果图像",
                "invoke_mode": "native",
                "recommended_action": "export_results",
                "params_schema": {"plot_tag": "string", "output_file": "string"},
                "examples": [{"action": "export_results"}],
            },
            {
                "category": "开发工具",
                "label": "官方 API 兜底调用",
                "invoke_mode": "native",
                "recommended_action": "call_official_api",
                "params_schema": {"method_name": "string", "args": "any[]", "target_path": "string|object[]?"},
                "examples": [{"action": "call_official_api", "params": {"method_name": "run"}}],
            },
        ]

    def get_ops_catalog(
        self,
        query: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
        *,
        wrappers_only: bool = False,
    ) -> Dict[str, Any]:
        try:
            native_items: List[Dict[str, Any]] = [] if wrappers_only else self._native_ops_catalog_items()

            wrapper_items: List[Dict[str, Any]] = []
            for wrapper_name, meta in (self._official_api_wrappers or {}).items():
                owner = meta.get("owner") or ""
                method_name = meta.get("method") or meta.get("method_name") or ""
                category = self._infer_category(owner, method_name, wrapper_name)
                wrapper_items.append(
                    {
                        "category": category,
                        "label": wrapper_name,
                        "invoke_mode": "wrapper",
                        "recommended_action": "call_official_api",
                        "params_schema": {
                            "model_path": "string",
                            "args": "any[]?",
                            "target_path": "string|object[]?",
                        },
                        "examples": [
                            {
                                "action": wrapper_name,
                                "owner": owner,
                                "method_name": method_name,
                            }
                        ],
                    }
                )

            items = wrapper_items if wrappers_only else (native_items + wrapper_items)
            if query:
                q = query.lower()

                def _item_text(item: Dict[str, Any]) -> str:
                    return (
                        f"{item.get('category','')} {item.get('label','')} "
                        f"{item.get('recommended_action','')} {item.get('invoke_mode','')}"
                    ).lower()

                items = [it for it in items if q in _item_text(it)]

            category_order = {c: i for i, c in enumerate(self._catalog_categories())}
            items.sort(
                key=lambda it: (
                    category_order.get(str(it.get("category")), 999),
                    str(it.get("label", "")).lower(),
                )
            )

            total = len(items)
            start = max(0, offset or 0)
            if limit is None or int(limit) <= 0:
                paged = items[start:]
            else:
                paged = items[start : start + int(limit)]

            return {
                "status": "success",
                "message": "ops catalog ready",
                "items": paged,
                "total": total,
                "limit": limit,
                "offset": offset,
                "categories": self._catalog_categories(),
            }
        except Exception as e:
            msg = self._normalize_comsol_error(e)
            logger.exception("get_ops_catalog failed")
            return {
                "status": "error",
                "message": msg,
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "categories": self._catalog_categories(),
            }

    @staticmethod
    def _normalize_tree_lines(node_tree: Any, limit: int = 80) -> List[str]:
        if node_tree is None:
            return []

        if isinstance(node_tree, (list, tuple)):
            raw_lines = [str(item) for item in node_tree]
        else:
            raw_lines = str(node_tree).splitlines()

        lines: List[str] = []
        seen: set[str] = set()
        for raw in raw_lines:
            line = re.sub(r"\s+", " ", str(raw or "")).strip(" \t|-:")
            if not line:
                continue
            low = line.lower()
            if low in seen:
                continue
            seen.add(low)
            lines.append(line)
            if len(lines) >= limit:
                break
        return lines

    @staticmethod
    def _tree_excerpt(tree_lines: List[str], keywords: List[str], limit: int = 6) -> List[str]:
        if not tree_lines:
            return []
        out: List[str] = []
        seen: set[str] = set()
        for line in tree_lines:
            low = line.lower()
            if not any(keyword in low for keyword in keywords):
                continue
            if low in seen:
                continue
            seen.add(low)
            out.append(line)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _infer_physics_purpose(tag: str) -> str:
        low = tag.lower()
        if "ht" in low or "heat" in low:
            return "负责热传导、热通量与温度场分布。"
        if "spf" in low or "flow" in low or "fluid" in low:
            return "负责流体连续性、动量守恒与流场求解。"
        if "solid" in low or "struct" in low or "beam" in low:
            return "负责结构响应、应力应变与位移场。"
        if "ec" in low or "es" in low or "electric" in low:
            return "负责电势、电流或静电场分布。"
        if "emw" in low or "mag" in low or "mf" in low:
            return "负责电磁场传播、磁场分布或耦合损耗。"
        if "tds" in low or "species" in low:
            return "负责组分输运、扩散和对流耦合。"
        return "负责该物理接口对应的控制方程与边界条件。"

    @staticmethod
    def _infer_material_role(tag: str) -> str:
        low = tag.lower()
        if "air" in low:
            return "通常用于环境域、流体域或对流换热背景介质。"
        if "cu" in low or "copper" in low:
            return "通常用于高导热或高导电部件。"
        if "si" in low or "silicon" in low:
            return "通常用于芯片、半导体或基底层。"
        if "steel" in low or "st" in low:
            return "通常用于承力结构、外壳或连接件。"
        return "为对应几何域提供密度、导热率、电导率等本构属性。"

    @staticmethod
    def _infer_study_purpose(tag: str) -> str:
        low = tag.lower()
        if "time" in low or "td" in low:
            return "用于分析系统的瞬态演化过程。"
        if "freq" in low:
            return "用于分析频域响应、幅值和相位。"
        if "eigen" in low:
            return "用于提取固有频率、模态或本征值。"
        if "param" in low:
            return "用于参数扫描和敏感性对比。"
        return "用于获得稳态或默认求解结果。"

    @staticmethod
    def _infer_result_purpose(tag: str) -> str:
        low = tag.lower()
        if "plot" in low:
            return "用于展示关键场变量分布。"
        if "table" in low:
            return "用于导出数值结果和对比指标。"
        if "export" in low:
            return "用于把图像、表格或数据导出到外部文件。"
        if "dataset" in low:
            return "用于组织求解数据与后处理输入。"
        return "用于承载结果后处理或验证输出。"

    def _build_geometry_setup(
        self, geom_tags: List[str], tree_lines: List[str]
    ) -> List[Dict[str, Any]]:
        excerpt = self._tree_excerpt(tree_lines, ["geom", "geometry", "workplane", "wp"])
        out: List[Dict[str, Any]] = []
        for tag in geom_tags:
            out.append(
                {
                    "tag": tag,
                    "role": "几何构建主序列",
                    "construction_clues": excerpt[:4],
                    "why": "几何序列定义了后续材料分配、物理场选择和网格生成的对象基础。",
                }
            )
        return out

    def _build_material_setup(
        self, material_tags: List[str], tree_lines: List[str]
    ) -> List[Dict[str, Any]]:
        excerpt = self._tree_excerpt(tree_lines, ["mat", "material"])
        return [
            {
                "tag": tag,
                "role": self._infer_material_role(tag),
                "selection_hint": excerpt[:3],
                "why": "材料属性会直接影响物理场方程中的本构关系与求解结果。",
            }
            for tag in material_tags
        ]

    def _build_physics_setup(
        self, physics_tags: List[str], tree_lines: List[str]
    ) -> List[Dict[str, Any]]:
        excerpt = self._tree_excerpt(
            tree_lines,
            ["physics", "multiphysics", "boundary", "ht", "spf", "solid", "emw"],
        )
        return [
            {
                "tag": tag,
                "category": self._infer_category("", tag),
                "purpose": self._infer_physics_purpose(tag),
                "tree_clues": excerpt[:4],
            }
            for tag in physics_tags
        ]

    def _build_mesh_setup(
        self, mesh_tags: List[str], tree_lines: List[str]
    ) -> List[Dict[str, Any]]:
        excerpt = self._tree_excerpt(tree_lines, ["mesh", "size", "swept", "free"])
        return [
            {
                "tag": tag,
                "role": "网格序列",
                "quality_hint": "建议在副本修改后重新生成网格并检查质量。",
                "tree_clues": excerpt[:4],
            }
            for tag in mesh_tags
        ]

    def _build_study_setup(
        self, study_tags: List[str], tree_lines: List[str]
    ) -> List[Dict[str, Any]]:
        excerpt = self._tree_excerpt(tree_lines, ["study", "solver", "time", "stationary", "freq"])
        return [
            {
                "tag": tag,
                "type": "study",
                "purpose": self._infer_study_purpose(tag),
                "tree_clues": excerpt[:4],
            }
            for tag in study_tags
        ]

    def _build_postprocess_setup(
        self, result_tags: List[str], tree_lines: List[str]
    ) -> List[Dict[str, Any]]:
        excerpt = self._tree_excerpt(tree_lines, ["result", "plot", "table", "dataset", "export"])
        return [
            {
                "tag": tag,
                "type": "result",
                "purpose": self._infer_result_purpose(tag),
                "tree_clues": excerpt[:4],
            }
            for tag in result_tags
        ]

    @staticmethod
    def _infer_design_intent(
        global_plans: List[GlobalDefinitionPlan],
        geom: List[str],
        mats: List[str],
        physics: List[str],
        meshes: List[str],
        studies: List[str],
        results: List[str],
        tree_lines: List[str],
    ) -> List[str]:
        out: List[str] = []
        if global_plans:
            out.append("模型先用全局参数管理关键尺寸或工况，说明设计目标包含复用性和参数化调优。")
        if geom:
            out.append("几何序列独立存在，说明几何构建与后续物理设置是分层组织的，便于在副本中局部替换结构。")
        if mats and physics:
            out.append("材料与物理场同时出现，说明模型依赖材料本构属性来闭合控制方程，而不是纯几何展示。")
        if meshes:
            out.append("单独保留网格序列，说明求解精度和收敛稳定性是显式设计的一部分。")
        if studies:
            out.append("研究节点被保留下来，说明模型已经明确了求解类型，而不是仅停留在前处理。")
        if results:
            out.append("结果节点被保存，说明模型不仅用于求解，还用于验证或复盘特定输出指标。")
        if any("selection" in line.lower() for line in tree_lines):
            out.append("树中出现 selection/选择集，说明原模型倾向于用可复用的域或边界集合来组织赋值与边界条件。")
        return out

    @staticmethod
    def _recommended_edit_workflow(
        source_model_path: Path,
        global_plans: List[GlobalDefinitionPlan],
        geom: List[str],
        mats: List[str],
        physics: List[str],
        meshes: List[str],
        studies: List[str],
    ) -> List[str]:
        out = [
            f"先基于 {source_model_path.name} 创建工作副本，不要直接覆盖原始下载模型。",
        ]
        if global_plans:
            names = ", ".join(item.name for item in global_plans[:6])
            out.append(f"优先检查并修改全局参数：{names}，因为这些参数最可能驱动尺寸、载荷或工况。")
        if geom:
            out.append(f"若需要改几何，先在几何序列 {', '.join(geom[:3])} 中调整特征，再重新检查相关选择集。")
        if mats:
            out.append(f"若修改材料，优先核对材料节点 {', '.join(mats[:3])} 的属性和分配域是否仍然匹配。")
        if physics:
            out.append(f"若修改物理场，重点核对接口 {', '.join(physics[:3])} 下的边界条件、初值和耦合关系。")
        if meshes:
            out.append("几何或材料修改后应重新生成网格，并检查网格质量是否仍适配当前求解。")
        if studies:
            out.append(f"最后复核研究节点 {', '.join(studies[:3])} 的求解类型与目标输出是否仍然成立。")
        return out

    @staticmethod
    def _build_case_context_block(
        source_model_path: Path,
        global_plans: List[GlobalDefinitionPlan],
        geom: List[str],
        mats: List[str],
        physics: List[str],
        meshes: List[str],
        studies: List[str],
        results: List[str],
        design_intent: List[str],
    ) -> str:
        def _bullet(items: List[str]) -> List[str]:
            return [f"- {item}" for item in items if str(item).strip()]

        lines: List[str] = [
            f"源模型: {source_model_path}",
            "",
            "全局参数",
        ]
        if global_plans:
            lines.extend(
                _bullet(
                    [
                        f"{item.name} = {item.value}"
                        + (f" ({item.description})" if item.description else "")
                        for item in global_plans[:12]
                    ]
                )
            )
        else:
            lines.append("- 未解析到全局参数")

        section_map = [
            ("几何序列", geom),
            ("材料节点", mats),
            ("物理场接口", physics),
            ("网格序列", meshes),
            ("研究节点", studies),
            ("结果节点", results),
        ]
        for title, items in section_map:
            lines.append("")
            lines.append(title)
            lines.extend(_bullet(items or ["未解析到相关节点"]))

        if design_intent:
            lines.append("")
            lines.append("设计意图推断")
            lines.extend(_bullet(design_intent[:8]))

        return "\n".join(lines).strip()

    @staticmethod
    def _build_copy_edit_prompt(
        source_model_path: Path,
        context_block: str,
        recommended_edit_workflow: List[str],
    ) -> str:
        lines = [
            "请基于这个本地 COMSOL 模型创建一个副本并继续修改，不要覆盖原始文件。",
            f"原始模型路径: {source_model_path}",
            "",
            "以下是解析出的模型上下文，可直接作为修改依据：",
            context_block,
        ]
        if recommended_edit_workflow:
            lines.extend(["", "建议修改顺序："])
            lines.extend(f"{index + 1}. {item}" for index, item in enumerate(recommended_edit_workflow[:8]))
        lines.extend(
            [
                "",
                "请先确认本轮想改的是参数、几何、材料、物理场、网格还是研究设置，然后给出修改计划。",
            ]
        )
        return "\n".join(lines).strip()

    @staticmethod
    def _infer_principles(physics_tags: List[str]) -> List[str]:
        out: List[str] = []
        text = " ".join(physics_tags).lower()
        if any(k in text for k in ["ht", "heat"]):
            out.append("Heat transfer and thermal energy balance")
        if any(k in text for k in ["emw", "electro", "mag"]):
            out.append("Electromagnetic field distribution and Joule losses")
        if any(k in text for k in ["solid", "struct", "beam"]):
            out.append("Solid mechanics and stress-strain response")
        if any(k in text for k in ["spf", "flow", "fluid", "cfd"]):
            out.append("Fluid flow continuity and momentum conservation")
        if not out:
            out.append("Multiphysics coupling with governing equations")
        return out

    @staticmethod
    def _infer_expected_behaviors(studies: List[str], physics_tags: List[str]) -> List[str]:
        out: List[str] = []
        studies_text = " ".join(studies).lower()
        if "time" in studies_text:
            out.append("Transient response over simulation time")
        if "freq" in studies_text:
            out.append("Frequency-domain amplitude/phase behavior")
        if "eigen" in studies_text:
            out.append("Eigenmodes and natural frequencies")
        if "stat" in studies_text or not out:
            out.append("Steady-state field distribution")
        if any("ht" in p.lower() or "heat" in p.lower() for p in physics_tags):
            out.append("Temperature gradients and heat flux paths")
        return out

    @staticmethod
    def _case_prompt(
        geom: List[str],
        mats: List[str],
        physics: List[str],
        studies: List[str],
        globals_count: int,
    ) -> str:
        geom_txt = ", ".join(geom) if geom else "default geometry sequence"
        mat_txt = ", ".join(mats) if mats else "material(s) to be specified"
        phy_txt = ", ".join(physics) if physics else "physics interface(s)"
        study_txt = ", ".join(studies) if studies else "stationary/time-dependent study"
        return (
            "请基于该案例建立一个 COMSOL 多物理场模型："
            f"几何节点={geom_txt}；材料={mat_txt}；物理场={phy_txt}；研究={study_txt}；"
            f"全局参数数量={globals_count}。"
            "先确认物理原理与目标指标，再输出三阶段建模规划并执行。"
        )

    def extract_model_operation_case(self, model_path: str) -> Dict[str, Any]:
        path = Path(model_path).resolve()
        if not path.exists():
            return {"status": "error", "message": f"model file not found: {path}"}
        if path.suffix.lower() != ".mph":
            return {"status": "error", "message": "only .mph files are supported"}

        tree_res = self.list_model_tree(str(path))
        if tree_res.get("status") != "success":
            return {
                "status": "error",
                "message": tree_res.get("message", "failed to read model tree"),
            }
        globals_res = self.list_global_parameters(str(path))
        if globals_res.get("status") != "success":
            return {
                "status": "error",
                "message": globals_res.get("message", "failed to read global parameters"),
            }
        node_tree_res = self.get_node_tree(str(path))

        tree = tree_res.get("tree", {}) or {}
        geom = [str(x) for x in (tree.get("geometries") or [])]
        mats = [str(x) for x in (tree.get("materials") or [])]
        physics = [str(x) for x in (tree.get("physics") or [])]
        meshes = [str(x) for x in (tree.get("meshes") or [])]
        studies = [str(x) for x in (tree.get("studies") or [])]
        results = [str(x) for x in (tree.get("results") or [])]
        node_tree_lines = self._normalize_tree_lines(
            node_tree_res.get("node_tree") if node_tree_res.get("status") == "success" else None
        )

        global_plans: List[GlobalDefinitionPlan] = []
        for item in globals_res.get("items", []) or []:
            try:
                global_plans.append(
                    GlobalDefinitionPlan(
                        name=str(item.get("name", "")),
                        value=str(item.get("value", "")),
                        unit=item.get("unit"),
                        description=item.get("description"),
                    )
                )
            except Exception:
                continue

        workflow_steps: List[Dict[str, Any]] = []
        if global_plans:
            workflow_steps.append(
                {
                    "stage": "define_globals",
                    "action": "define_globals",
                    "count": len(global_plans),
                }
            )
        if geom:
            workflow_steps.append({"stage": "geometry", "action": "create_geometry", "targets": geom})
        if mats:
            workflow_steps.append({"stage": "material", "action": "add_material", "targets": mats})
        if physics:
            workflow_steps.append({"stage": "physics", "action": "add_physics", "targets": physics})
        if meshes:
            workflow_steps.append({"stage": "mesh", "action": "generate_mesh", "targets": meshes})
        if studies:
            workflow_steps.append({"stage": "study", "action": "configure_study", "targets": studies})
        if results:
            workflow_steps.append(
                {"stage": "postprocess", "action": "export_results", "targets": results}
            )

        geometry_setup = self._build_geometry_setup(geom, node_tree_lines)
        material_setup = self._build_material_setup(mats, node_tree_lines)
        physics_setup = self._build_physics_setup(physics, node_tree_lines)
        mesh_setup = self._build_mesh_setup(meshes, node_tree_lines)
        study_setup = self._build_study_setup(studies, node_tree_lines)
        postprocess_setup = self._build_postprocess_setup(results, node_tree_lines)
        design_intent = self._infer_design_intent(
            global_plans=global_plans,
            geom=geom,
            mats=mats,
            physics=physics,
            meshes=meshes,
            studies=studies,
            results=results,
            tree_lines=node_tree_lines,
        )
        recommended_edit_workflow = self._recommended_edit_workflow(
            source_model_path=path,
            global_plans=global_plans,
            geom=geom,
            mats=mats,
            physics=physics,
            meshes=meshes,
            studies=studies,
        )
        context_block = self._build_case_context_block(
            source_model_path=path,
            global_plans=global_plans,
            geom=geom,
            mats=mats,
            physics=physics,
            meshes=meshes,
            studies=studies,
            results=results,
            design_intent=design_intent,
        )
        copy_edit_prompt = self._build_copy_edit_prompt(
            source_model_path=path,
            context_block=context_block,
            recommended_edit_workflow=recommended_edit_workflow,
        )

        case = ModelOperationCase(
            case_id=f"case-{uuid4().hex[:12]}",
            source_model_path=str(path),
            summary=(
                f"已完成 {path.name} 的本地模型剖析："
                f"{len(global_plans)} 个全局参数、{len(geom)} 个几何序列、"
                f"{len(mats)} 个材料节点、{len(physics)} 个物理场接口、"
                f"{len(meshes)} 个网格序列、{len(studies)} 个研究节点、"
                f"{len(results)} 个结果节点。"
            ),
            physical_principles=self._infer_principles(physics),
            expected_behaviors=self._infer_expected_behaviors(studies, physics),
            global_definitions=global_plans,
            workflow_steps=workflow_steps,
            geometry_setup=geometry_setup,
            material_setup=material_setup,
            physics_setup=physics_setup,
            mesh_setup=mesh_setup,
            study_setup=study_setup,
            postprocess_setup=postprocess_setup,
            design_intent=design_intent,
            recommended_edit_workflow=recommended_edit_workflow,
            context_block=context_block,
            copy_edit_prompt=copy_edit_prompt,
            node_tree_excerpt=node_tree_lines[:18],
            reusable_user_prompt=self._case_prompt(
                geom=geom,
                mats=mats,
                physics=physics,
                studies=studies,
                globals_count=len(global_plans),
            ),
            extracted_at=datetime.now(),
        )
        return {
            "status": "success",
            "message": "model operation case extracted",
            "case": case.model_dump(mode="json"),
        }
