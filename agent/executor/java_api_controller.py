"""Java API 控制器 - 混合模式控制 Java API 调用（支持材料、3D、扩展物理场）"""

import base64
import importlib.util
import re
import shutil
import tempfile
from html import unescape
from pathlib import Path
from types import MethodType
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from agent.executor.comsol_runner import COMSOLRunner
from agent.utils.config import get_settings
from agent.utils.logger import get_logger
from schemas.material import MaterialDefinition, MaterialPlan
from schemas.physics import PhysicsPlan
from schemas.study import StudyPlan

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
        feat.propertyGroup("Def").set("k", k_val)
    except Exception:
        pass


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
        self.comsol_runner = COMSOLRunner()
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

    @staticmethod
    def _physics_api(model):
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
        out = {"materials": [], "physics": [], "studies": [], "meshes": [], "geometries": []}
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
            else:
                group = mat_def.property_group or "Def"
                prop_names_lower = [p.name.strip().lower() for p in mat_def.properties]
                has_k = any(
                    n in ("k", "thermalconductivity", "thermal conductivity")
                    for n in prop_names_lower
                )
                for prop in mat_def.properties:
                    name_to_set = MATERIAL_PROPERTY_COMSOL_ALIAS.get(prop.name, prop.name)
                    try:
                        feat.propertyGroup(group).set(name_to_set, prop.value)
                    except Exception:
                        try:
                            feat.propertyGroup(group).set(prop.name, prop.value)
                        except Exception as e2:
                            logger.warning(
                                "设置材料属性 %s（或 %s）失败: %s", prop.name, name_to_set, e2
                            )
                if not has_k:
                    _ensure_material_thermal_k(feat, mat_def)
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
            # Boundary conditions
            for bc in field.boundary_conditions:
                try:
                    ph_feat.create(bc.name, bc.condition_type)
                    if isinstance(bc.selection, list) and bc.selection:
                        ph_feat.feature(bc.name).selection().set(bc.selection)
                    for k, v in bc.parameters.items():
                        ph_feat.feature(bc.name).set(k, v)
                except Exception as e:
                    failures.append(
                        {
                            "kind": "boundary_condition",
                            "interface": name,
                            "name": bc.name,
                            "error": str(e),
                        }
                    )
                    logger.warning("设置边界条件 %s 失败: %s", bc.name, e)

            # Domain conditions
            for dc in field.domain_conditions:
                try:
                    ph_feat.create(dc.name, dc.condition_type)
                    if isinstance(dc.selection, list) and dc.selection:
                        ph_feat.feature(dc.name).selection().set(dc.selection)
                    for k, v in dc.parameters.items():
                        ph_feat.feature(dc.name).set(k, v)
                except Exception as e:
                    failures.append(
                        {
                            "kind": "domain_condition",
                            "interface": name,
                            "name": dc.name,
                            "error": str(e),
                        }
                    )
                    logger.warning("设置域条件 %s 失败: %s", dc.name, e)

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

        return {"interfaces": added, "failures": failures}

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
    ) -> Dict[str, Any]:
        logger.info("执行求解...")
        try:
            model = self._load_model(model_path)
            study_name = self._solve_direct(model)
            if save_to_path:
                saved_path = _save_model_to_new_path(model, Path(save_to_path))
            else:
                saved_path = _save_model_avoid_lock(
                    model, Path(model_path), allow_fallback=not run_single_file
                )
            out = {"status": "success", "message": "求解成功", "result": {"study": study_name}}
            out["saved_path"] = str(saved_path.resolve())
            return out
        except Exception as e:
            logger.error(f"求解失败: {e}")
            return {"status": "error", "message": str(e)}

    def _solve_direct(self, model) -> str:
        tags = model.study().tags()
        if not tags:
            raise RuntimeError("模型中没有研究，请先配置研究")
        study_name = tags[0]
        model.study(study_name).run()
        return study_name

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
                target = self.comsol_runner.invoke_java_method(target, method_name, *args)
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
                target = self.comsol_runner.invoke_java_method(target, method_name, *args)
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
            result = self.comsol_runner.invoke_java_method(target, method_name, *(args or []))
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
            result = self.comsol_runner.invoke_static_api(class_name, method_name, *(args or []))
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
