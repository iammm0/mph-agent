"""Java API 控制器 - 混合模式控制 Java API 调用（支持材料、3D、扩展物理场）"""
from pathlib import Path
from typing import Dict, Any, Optional, List
import base64
import shutil
import tempfile

from agent.executor.comsol_runner import COMSOLRunner
from agent.executor.java_generator import JavaGenerator
from agent.utils.logger import get_logger
from agent.utils.config import get_settings
from schemas.physics import PhysicsPlan
from schemas.study import StudyPlan
from schemas.material import MaterialPlan

logger = get_logger(__name__)


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


def _save_model_avoid_lock(model, dest_path: Path):
    """保存 model 到 dest_path。先写临时文件再替换；若目标被占用则写入备用路径。"""
    import os
    dest_path = Path(dest_path).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".mph", prefix=dest_path.stem + "_", dir=str(dest_path.parent))
    try:
        os.close(fd)
    except Exception:
        pass
    tmp_path = Path(tmp_path)
    try:
        model.save(tmp_path.as_posix())
        try:
            tmp_path.replace(dest_path)
            return dest_path
        except OSError as e:
            if getattr(e, "winerror", None) == 32:
                fallback = dest_path.parent / (dest_path.stem + "_updated.mph")
                shutil.copy2(str(tmp_path), str(fallback))
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
                logger.info(f"原文件被占用，已保存到: {fallback}")
                return fallback
            raise
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


class JavaAPIController:
    """Java API 控制器 - 根据操作复杂度选择直接调用或代码生成"""

    def __init__(self):
        self.settings = get_settings()
        self.comsol_runner = COMSOLRunner()
        self.java_generator = JavaGenerator()

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
            if model.component().has("comp1") and hasattr(model.component("comp1"), "material"):
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
            if model.component().has("comp1"):
                return model.component("comp1").material(name)
        except Exception as e:
            raise RuntimeError(f"获取材料节点 '{name}' 失败: {e}") from e
        raise RuntimeError("当前 COMSOL 模型不支持材料节点访问")

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
                            for prop in ("nu", "E", "density", "thermalconductivity", "specificheat", "youngsmodulus", "poissonsratio"):
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
            return {"status": "success", "message": f"已重命名 {old_name} -> {new_name}", "old_name": old_name, "new_name": new_name}
        except Exception as e:
            logger.warning("rename_material 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def update_material_properties(self, model_path: str, name: str, properties: Dict[str, Any], property_group: str = "Def") -> Dict[str, Any]:
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
                    except Exception as e1:
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
                return {"status": "error", "message": "当前 COMSOL 版本不支持 materials().remove()", "removed": []}
            for tag in tags:
                try:
                    mat_seq.remove(tag)
                except Exception as e:
                    logger.warning("删除材料 %s 失败: %s", tag, e)
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已删除 {len(tags)} 个材料节点", "removed": tags}
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
                if hasattr(model, "physics"):
                    out["physics"] = self._tags_or_names(model.physics())
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
                if model.component().has("comp1") and hasattr(model.component("comp1").geom(), "tags"):
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
                    return list(n) if not isinstance(n, (list, tuple)) else n
            except Exception:
                pass
        if hasattr(seq, "tags"):
            try:
                t = seq.tags()
                if t is not None:
                    return list(t) if not isinstance(t, (list, tuple)) else t
            except Exception:
                pass
        return []

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
                return {"status": "error", "message": "当前 COMSOL 版本不支持 study(tag).name(newName)"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已重命名研究 {old_name} -> {new_name}", "old_name": old_name, "new_name": new_name}
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
                return {"status": "error", "message": "当前 COMSOL 版本不支持 hasNode(path)", "exists": False}
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
            ph = model.physics()
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
            if hasattr(model.physics(), "remove"):
                model.physics().remove(name)
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
            ph = model.physics()
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
            ph = model.physics()
            if hasattr(ph, "has") and not ph.has(old_name):
                return {"status": "error", "message": f"物理场节点不存在: {old_name}"}
            if hasattr(ph, "has") and ph.has(new_name):
                return {"status": "error", "message": f"目标名称已存在: {new_name}"}
            feat = model.physics(old_name)
            if hasattr(feat, "name"):
                feat.name(new_name)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 physics(tag).name(newName)"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已重命名物理场 {old_name} -> {new_name}", "old_name": old_name, "new_name": new_name}
        except Exception as e:
            logger.warning("rename_physics 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def clear_physics(self, model_path: str) -> Dict[str, Any]:
        """清除所有物理场节点。API: model.physics().clear()."""
        try:
            model = self._load_model(model_path)
            ph = model.physics()
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
                    return {"status": "error", "message": "当前 COMSOL 版本不支持 physics().clear() 或 remove()"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": "已清除所有物理场节点"}
        except Exception as e:
            logger.warning("clear_physics 失败: %s", e)
            return {"status": "error", "message": str(e)}

    def physics_feature_is_active(self, model_path: str, physics_tag: str, feature_tag: str) -> Dict[str, Any]:
        """检查物理场下某特征是否已激活。API: model.physics(\"ht0\").feature(\"temp1\").isActive()."""
        try:
            model = self._load_model(model_path)
            feat = model.physics(physics_tag).feature(feature_tag)
            active = feat.isActive() if hasattr(feat, "isActive") else True
            return {"status": "success", "active": bool(active), "physics": physics_tag, "feature": feature_tag}
        except Exception as e:
            logger.warning("physics_feature_is_active 失败: %s", e)
            return {"status": "error", "message": str(e), "active": False}

    def set_physics_feature_param(self, model_path: str, physics_tag: str, feature_tag: str, key: str, value: Any) -> Dict[str, Any]:
        """修改已存在边界条件/特征参数。API: model.physics(\"ht0\").feature(\"temp1\").set(\"T0\", \"293.15\")."""
        try:
            model = self._load_model(model_path)
            feat = model.physics(physics_tag).feature(feature_tag)
            feat.set(key, value)
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已设置 {physics_tag}.{feature_tag}.{key}", "physics": physics_tag, "feature": feature_tag, "key": key}
        except Exception as e:
            logger.warning("set_physics_feature_param 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== 几何节点：查询 =====

    def list_geometry_tags(self, model_path: str) -> Dict[str, Any]:
        """查询几何节点名称列表。API: model.geom().names() 或 .tags()；component 下为 component('comp1').geom()。"""
        try:
            model = self._load_model(model_path)
            if model.component().has("comp1"):
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
            if model.component().has("comp1"):
                geom_seq = model.component("comp1").geom()
            if geom_seq is None or not hasattr(geom_seq, "has"):
                geom_seq = model.geom()
            if hasattr(geom_seq, "has") and not geom_seq.has(old_name):
                return {"status": "error", "message": f"几何节点不存在: {old_name}"}
            if hasattr(geom_seq, "has") and geom_seq.has(new_name):
                return {"status": "error", "message": f"目标名称已存在: {new_name}"}
            if model.component().has("comp1"):
                feat = model.component("comp1").geom(old_name)
            else:
                feat = model.geom(old_name)
            if hasattr(feat, "name"):
                feat.name(new_name)
            else:
                return {"status": "error", "message": "当前 COMSOL 版本不支持 geom(tag).name(newName)"}
            _save_model_avoid_lock(model, Path(model_path))
            return {"status": "success", "message": f"已重命名几何 {old_name} -> {new_name}", "old_name": old_name, "new_name": new_name}
        except Exception as e:
            logger.warning("rename_geometry 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== Selection（选择集）=====

    def _selection_api(self, model):
        """获取 selection 列表 API：model.selection() 或 component 下 component('comp1').selection()。"""
        try:
            if hasattr(model, "selection"):
                return model.selection()
            if model.component().has("comp1") and hasattr(model.component("comp1"), "selection"):
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
            sel = sel_list.get(tag) if hasattr(sel_list, "get") else getattr(sel_list, tag) if hasattr(sel_list, tag) else None
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
            return {"status": "success", "message": f"已重命名选择集 {old_name} -> {new_name}", "old_name": old_name, "new_name": new_name}
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
            geom_seq = model.component("comp1").geom() if model.component().has("comp1") else model.geom()
            if not hasattr(geom_seq, "has") or not geom_seq.has(geom_tag):
                return {"status": "error", "message": f"几何节点不存在: {geom_tag}"}
            geom = model.component("comp1").geom(geom_tag) if model.component().has("comp1") else model.geom(geom_tag)
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
            return {"status": "success", "message": f"已导入几何 {path.name}", "feature": feat_tag, "path": str(path)}
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
            geom_seq = model.component("comp1").geom() if model.component().has("comp1") else model.geom()
            if not hasattr(geom_seq, "has") or not geom_seq.has(geom_tag):
                return {"status": "error", "message": f"几何节点不存在: {geom_tag}"}
            geom = model.component("comp1").geom(geom_tag) if model.component().has("comp1") else model.geom(geom_tag)
            if not hasattr(geom, "measure"):
                return {"status": "error", "message": "当前 COMSOL 版本不支持 geom.measure()"}
            measure = geom.measure()
            if not hasattr(measure, "getVolume") and not hasattr(measure, "getArea") and not hasattr(measure, "getLength"):
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
            return {"status": "success", "value": float(value) if value is not None else None, "what": what}
        except Exception as e:
            logger.warning("geometry_measure 失败: %s", e)
            return {"status": "error", "message": str(e)}

    # ===== 网格高级 =====

    def _mesh_api(self, model):
        """获取 mesh 列表：model.mesh() 或 component('comp1').mesh()。"""
        try:
            if model.component().has("comp1") and hasattr(model.component("comp1"), "mesh"):
                return model.component("comp1").mesh()
            if hasattr(model, "mesh"):
                return model.mesh()
        except Exception as e:
            raise RuntimeError(f"COMSOL mesh API 不可用: {e}") from e
        raise RuntimeError("当前 COMSOL 模型无 mesh() 接口")

    def mesh_create(self, model_path: str, tag: str = "mesh1", geom_tag: str = "geom1") -> Dict[str, Any]:
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

    def mesh_set_size(self, model_path: str, mesh_tag: str = "mesh1", hauto: Optional[int] = None, hmax: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
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

    def clear_solution_data(self, model_path: str, solver_tag: Optional[str] = None) -> Dict[str, Any]:
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

    def table_export(self, model_path: str, table_tag: str, out_path: str, **kwargs: Any) -> Dict[str, Any]:
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

    def add_materials(self, model_path: str, material_plan: MaterialPlan) -> Dict[str, Any]:
        """添加材料到模型"""
        logger.info("添加材料...")
        try:
            model = self._load_model(model_path)
            result = self._add_materials_direct(model, material_plan)
            saved_path = _save_model_avoid_lock(model, Path(model_path))
            out = {"status": "success", "message": "材料设置成功", "result": result}
            if saved_path != Path(model_path):
                out["saved_path"] = str(saved_path)
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
            else:
                group = mat_def.property_group or "Def"
                for prop in mat_def.properties:
                    name_to_set = MATERIAL_PROPERTY_COMSOL_ALIAS.get(prop.name, prop.name)
                    try:
                        feat.propertyGroup(group).set(name_to_set, prop.value)
                    except Exception as e1:
                        try:
                            feat.propertyGroup(group).set(prop.name, prop.value)
                        except Exception as e2:
                            logger.warning("设置材料属性 %s（或 %s）失败: %s", prop.name, name_to_set, e2)
            added.append({"material": actual_name, "label": mat_def.label, "requested_name": mat_def.name})

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

    def add_physics(self, model_path: str, physics_plan: PhysicsPlan) -> Dict[str, Any]:
        logger.info("添加物理场...")
        try:
            model = self._load_model(model_path)
            result = self._add_physics_direct(model, physics_plan)
            saved_path = _save_model_avoid_lock(model, Path(model_path))
            out = {"status": "success", "message": "物理场设置成功", "result": result}
            if saved_path != Path(model_path):
                out["saved_path"] = str(saved_path)
            return out
        except Exception as e:
            logger.error(f"添加物理场失败: {e}")
            return {"status": "error", "message": str(e)}

    def _add_physics_direct(self, model, physics_plan: PhysicsPlan) -> Dict[str, Any]:
        self._ensure_geometry_built(model)
        geom_tag = "geom1"
        added = []
        for i, field in enumerate(physics_plan.fields):
            tag = PHYSICS_TYPE_TO_COMSOL_TAG.get(field.type, "HeatTransfer")
            name = self._physics_interface_name(field.type, i)
            try:
                if model.component().has("comp1"):
                    model.component("comp1").physics().create(name, tag, geom_tag)
                else:
                    model.physics().create(name, tag, geom_tag)
            except Exception:
                model.physics().create(name, tag, geom_tag)

            # Boundary conditions
            for bc in field.boundary_conditions:
                try:
                    model.physics(name).create(bc.name, bc.condition_type)
                    if isinstance(bc.selection, list) and bc.selection:
                        model.physics(name).feature(bc.name).selection().set(bc.selection)
                    for k, v in bc.parameters.items():
                        model.physics(name).feature(bc.name).set(k, v)
                except Exception as e:
                    logger.warning("设置边界条件 %s 失败: %s", bc.name, e)

            # Domain conditions
            for dc in field.domain_conditions:
                try:
                    model.physics(name).create(dc.name, dc.condition_type)
                    if isinstance(dc.selection, list) and dc.selection:
                        model.physics(name).feature(dc.name).selection().set(dc.selection)
                    for k, v in dc.parameters.items():
                        model.physics(name).feature(dc.name).set(k, v)
                except Exception as e:
                    logger.warning("设置域条件 %s 失败: %s", dc.name, e)

            # Initial conditions
            for ic in field.initial_conditions:
                try:
                    model.physics(name).feature("init1").set(ic.variable, ic.value)
                except Exception:
                    try:
                        model.physics(name).create(ic.name, "init")
                        model.physics(name).feature(ic.name).set(ic.variable, ic.value)
                    except Exception as e:
                        logger.warning("设置初始条件 %s 失败: %s", ic.name, e)

            added.append({"interface": name, "type": field.type, "tag": tag})

        # Multi-physics couplings
        for coupling in physics_plan.couplings:
            ctag = COUPLING_TYPE_TO_COMSOL_TAG.get(coupling.type, coupling.type)
            try:
                model.multiphysics().create(coupling.type, ctag)
            except Exception as e:
                logger.warning("创建耦合 %s 失败: %s", coupling.type, e)

        return {"interfaces": added}

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
        try:
            if model.component().has("comp1") and model.component("comp1").geom().has("geom1"):
                model.component("comp1").geom("geom1").run()
                return
        except Exception:
            pass
        try:
            if model.geom().has("geom1"):
                model.geom("geom1").run()
        except Exception:
            pass

    # ===== Mesh =====

    def generate_mesh(self, model_path: str, mesh_params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("生成网格...")
        try:
            model = self._load_model(model_path)
            self._generate_mesh_direct(model, mesh_params or {})
            saved_path = _save_model_avoid_lock(model, Path(model_path))
            out = {"status": "success", "message": "网格划分成功", "result": {}}
            if saved_path != Path(model_path):
                out["saved_path"] = str(saved_path)
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
            if model.component().has("comp1"):
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

    def configure_study(self, model_path: str, study_plan: StudyPlan) -> Dict[str, Any]:
        logger.info("配置研究...")
        try:
            model = self._load_model(model_path)
            result = self._configure_study_direct(model, study_plan)
            saved_path = _save_model_avoid_lock(model, Path(model_path))
            out = {"status": "success", "message": "研究配置成功", "result": result}
            if saved_path != Path(model_path):
                out["saved_path"] = str(saved_path)
            return out
        except Exception as e:
            logger.error(f"配置研究失败: {e}")
            return {"status": "error", "message": str(e)}

    def _configure_study_direct(self, model, study_plan: StudyPlan) -> Dict[str, Any]:
        added = []
        for i, st in enumerate(study_plan.studies):
            step_type = STUDY_TYPE_TO_COMSOL_TAG.get(st.type, "Stationary")
            name = f"std{i + 1}"
            model.study().create(name)
            model.study(name).create("std", step_type)

            if st.parametric_sweep:
                ps = st.parametric_sweep
                try:
                    model.study(name).create("param", "Parametric")
                    model.study(name).feature("param").set("pname", ps.parameter_name)
                    model.study(name).feature("param").set("prange",
                        f"range({ps.range_start},{ps.step or ''},{ps.range_end})")
                except Exception as e:
                    logger.warning("参数化扫描配置失败: %s", e)

            added.append({"study": name, "type": st.type, "tag": step_type})
        return {"studies": added}

    # ===== Solve =====

    def solve(self, model_path: str) -> Dict[str, Any]:
        logger.info("执行求解...")
        try:
            model = self._load_model(model_path)
            study_name = self._solve_direct(model)
            saved_path = _save_model_avoid_lock(model, Path(model_path))
            out = {"status": "success", "message": "求解成功", "result": {"study": study_name}}
            if saved_path != Path(model_path):
                out["saved_path"] = str(saved_path)
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

    def execute_direct(self, operation: str, model_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
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

    def validate_execution(self, model_path: str, expected_result: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not Path(model_path).exists():
                return {"status": "error", "message": "模型文件不存在"}
            return {"status": "success", "message": "验证通过"}
        except Exception as e:
            return {"status": "error", "message": f"验证失败: {e}"}

    # ===== 模型预览（导出几何/结果图为 PNG，供桌面端显示）=====

    def export_model_preview(self, model_path: str, width: int = 640, height: int = 480) -> Dict[str, Any]:
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
            if model.component().has("comp1") and model.component("comp1").geom().has("geom1"):
                return model.component("comp1").geom("geom1")
        except Exception:
            pass
        try:
            if model.geom().has("geom1"):
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
        model.physics(physics_name).create(boundary_name, condition_type)
        for k, v in parameters.get("params", {}).items():
            model.physics(physics_name).feature(boundary_name).set(k, v)
        return {"physics": physics_name, "boundary": boundary_name, "type": condition_type}
