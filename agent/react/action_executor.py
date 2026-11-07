"""行动执行器 — 支持材料、3D 几何"""

import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.core.events import EventType
from agent.executor.comsol_runner import COMSOLRunner
from agent.executor.java_api_controller import (
    DEFAULT_THERMAL_K_SOLID,
    JavaAPIController,
)
from agent.planner.geometry_agent import GeometryAgent
from agent.planner.material_agent import MaterialAgent
from agent.planner.physics_agent import PhysicsAgent
from agent.planner.study_agent import StudyAgent
from agent.utils.logger import get_logger
from agent.schemas.task import ExecutionStep, GlobalDefinitionPlan, ReActTaskPlan

logger = get_logger(__name__)
GLOBAL_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")
# 分阶段落盘后缀；成功后只保留 {base}_latest.mph
_STAGE_MODEL_SUFFIXES = (
    "_geometry",
    "_global",
    "_material",
    "_physics",
    "_mesh",
    "_study",
    "_solve",
)


class ActionExecutor:
    """行动执行器 - 执行具体的建模操作"""

    def __init__(
        self,
        event_bus: Optional[Any] = None,
        context_manager: Optional[Any] = None,
        error_collector: Optional[Any] = None,
    ):
        self._comsol_runner: Optional[COMSOLRunner] = None
        self._java_api_controller: Optional[JavaAPIController] = None
        self._event_bus = event_bus
        self._context_manager = context_manager
        self._error_collector = error_collector

        self._geometry_agent = None
        self._physics_agent = None
        self._material_agent = None
        self._study_agent = None

    def _get_comsol_runner(self) -> COMSOLRunner:
        if self._comsol_runner is None:
            self._comsol_runner = COMSOLRunner()
        return self._comsol_runner

    def _get_java_api_controller(self) -> JavaAPIController:
        if self._java_api_controller is None:
            self._java_api_controller = JavaAPIController()
        return self._java_api_controller

    @staticmethod
    def _stage_base(plan: ReActTaskPlan) -> Tuple[Path, str]:
        """返回 (输出目录, 基础名)，用于按阶段命名：base_geometry.mph, base_material.mph, base_latest.mph。"""
        if getattr(plan, "model_path", None):
            p = Path(plan.model_path)
            parent = p.parent
            stem = p.stem
            for suffix in (
                "_latest",
                "_geometry",
                "_global",
                "_material",
                "_physics",
                "_mesh",
                "_study",
                "_solve",
            ):
                if stem.endswith(suffix):
                    base_name = stem[: -len(suffix)]
                    return parent, base_name
            return parent, stem
        base_name = (getattr(plan, "model_name", None) or "model").replace(".mph", "").strip()
        out = getattr(plan, "output_dir", None)
        if isinstance(out, (str, Path)):
            parent = Path(out).resolve()
        else:
            parent = Path.cwd()
        return parent, base_name

    def _stage_path(self, plan: ReActTaskPlan, stage: str) -> str:
        """本阶段的模型路径（新文件），避免覆盖已打开文件。"""
        base_dir, base_name = self._stage_base(plan)
        return str(base_dir / f"{base_name}_{stage}.mph")

    def _update_latest(self, plan: ReActTaskPlan) -> None:
        """将当前 model_path 复制为 base_latest.mph 并设为 plan.model_path，标识最新模型。"""
        if not getattr(plan, "model_path", None):
            return
        src = Path(plan.model_path)
        if not src.exists():
            return
        base_dir, base_name = self._stage_base(plan)
        latest = base_dir / f"{base_name}_latest.mph"
        try:
            if src.resolve() != latest.resolve():
                shutil.copy2(str(src), str(latest))
            plan.model_path = str(latest.resolve())
        except Exception as e:
            logger.warning("更新 _latest 副本失败: %s", e)

    def cleanup_stage_models(self, plan: ReActTaskPlan) -> Dict[str, Any]:
        """
        删除同 base 的过程模型（geometry/material/.../solve），只保留 *_latest.mph。
        求解成功或整轮成功结束时调用。
        """
        if not getattr(plan, "model_path", None):
            return {"removed": [], "kept": None}
        # 先确保 latest 是当前内容
        self._update_latest(plan)
        base_dir, base_name = self._stage_base(plan)
        latest = (base_dir / f"{base_name}_latest.mph").resolve()
        if not latest.exists():
            return {"removed": [], "kept": None}

        removed: list[str] = []
        for suffix in _STAGE_MODEL_SUFFIXES:
            for candidate in (
                base_dir / f"{base_name}{suffix}.mph",
                base_dir / f"{base_name}{suffix}.mph.lock",
            ):
                try:
                    if not candidate.exists():
                        continue
                    if candidate.resolve() == latest:
                        continue
                    candidate.unlink()
                    removed.append(str(candidate))
                except Exception as e:
                    logger.warning("删除过程模型失败 %s: %s", candidate, e)

        # 顺带清掉孤立 .lock
        lock = Path(str(latest) + ".lock")
        try:
            if lock.exists():
                lock.unlink()
                removed.append(str(lock))
        except Exception:
            pass

        plan.model_path = str(latest)
        if self._context_manager and hasattr(self._context_manager, "set_latest_model"):
            try:
                self._context_manager.set_latest_model(str(latest))
            except Exception:
                pass
        if removed:
            logger.info(
                "已清理 %d 个过程模型，保留: %s", len(removed), latest
            )
        return {"removed": removed, "kept": str(latest)}

    def _emit_step_start(self, step_type: str, message: str = "") -> None:
        """向交互板块发送步骤开始事件，便于逐步渲染。"""
        if self._event_bus:
            self._event_bus.emit_type(
                EventType.STEP_START,
                {"step_type": step_type, "message": message or f"正在执行{step_type}..."},
            )

    def _emit_step_end(self, step_type: str, message: str, **extra: Any) -> None:
        """向交互板块发送步骤结束事件。"""
        if self._event_bus:
            data: Dict[str, Any] = {"step_type": step_type, "message": message, **extra}
            self._event_bus.emit_type(EventType.STEP_END, data)

    def execute(
        self,
        plan: ReActTaskPlan,
        step: ExecutionStep,
        thought: Dict[str, Any],
    ) -> Dict[str, Any]:
        logger.info(f"执行步骤: {step.action} ({step.step_type})")
        if self._context_manager:
            self._context_manager.append_operation(
                "动作开始",
                f"{step.action} ({step.step_type})",
                "running",
                getattr(plan, "model_path", None),
            )

        action_handlers = {
            "create_geometry": self.execute_geometry,
            "define_globals": self.execute_define_globals,
            "add_material": self.execute_material,
            "update_material_property": self.execute_update_material_property,
            "add_physics": self.execute_physics,
            "generate_mesh": self.execute_mesh,
            "configure_study": self.execute_study,
            "solve": self.execute_solve,
            "import_geometry": self.execute_import_geometry,
            "create_selection": self.execute_create_selection,
            "export_results": self.execute_export_results,
            "evaluate_results": self.execute_evaluate_results,
            "set_parameters": self.execute_set_parameters,
            "call_official_api": self.execute_call_official_api,
            "retry": self.execute_retry,
            "skip": self.execute_skip,
        }

        handler = action_handlers.get(step.action)
        if not handler:
            if self._context_manager:
                self._context_manager.append_operation(
                    "动作失败",
                    f"未知行动: {step.action}",
                    "error",
                    getattr(plan, "model_path", None),
                )
            return {"status": "error", "message": f"未知的行动: {step.action}"}

        try:
            result = handler(plan, step, thought)
            if self._context_manager:
                self._context_manager.append_operation(
                    "动作结束",
                    f"{step.action} ({step.step_type})",
                    str(result.get("status", "unknown")),
                    getattr(plan, "model_path", None),
                )
            return result
        except Exception as e:
            logger.error(f"执行步骤失败: {e}")
            if self._context_manager:
                self._context_manager.append_operation(
                    "动作异常",
                    f"{step.action} ({step.step_type}) - {e}",
                    "error",
                    getattr(plan, "model_path", None),
                )
            if self._error_collector:
                self._error_collector.submit(
                    step.step_id, "exception", {"message": str(e), "step_type": step.step_type}
                )
            return {"status": "error", "message": str(e)}

    # ===== Geometry =====

    def execute_geometry(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行几何建模...")
        self._emit_step_start("几何建模", "正在创建几何...")

        geometry_plan = getattr(plan, "geometry_plan", None)
        if not geometry_plan:
            if not self._geometry_agent:
                self._geometry_agent = GeometryAgent()
            geometry_input = (
                thought.get("parameters", {}).get("geometry_input")
                or getattr(plan, "user_input", "")
                or ""
            )
            geometry_plan = self._geometry_agent.parse(geometry_input)
            plan.geometry_plan = geometry_plan

        plan.dimension = geometry_plan.dimension
        _, base_name = self._stage_base(plan)
        output_filename = f"{base_name}_geometry.mph"
        output_dir = getattr(plan, "output_dir", None)
        out_path = Path(output_dir) if isinstance(output_dir, (str, Path)) and output_dir else None
        try:
            runner = self._get_comsol_runner()
            if out_path is not None:
                model_path = runner.create_model_from_plan(
                    geometry_plan, output_filename, output_dir=out_path
                )
            else:
                model_path = runner.create_model_from_plan(geometry_plan, output_filename)
        except Exception as e:
            logger.error(f"几何建模失败: {e}")
            return {"status": "error", "message": f"几何建模失败: {e}"}
        plan.model_path = str(model_path)
        self._update_latest(plan)
        if self._context_manager:
            self._context_manager.append_operation(
                "几何建模", f"几何建模成功 ({geometry_plan.dimension}D)", "success", str(model_path)
            )
        if self._event_bus:
            self._event_bus.emit_type(
                EventType.GEOMETRY_3D,
                {
                    "message": f"几何建模成功 ({geometry_plan.dimension}D)",
                    "dimension": geometry_plan.dimension,
                    "model_path": str(model_path),
                },
            )
        ui = {
            "action": "创建/编辑几何",
            "detail": f"根据几何计划创建 {geometry_plan.dimension}D 几何并保存模型",
            "target": f"几何: geom1, 形状数: {len(getattr(geometry_plan, 'shapes', []))}",
        }
        return {
            "status": "success",
            "message": f"几何建模成功 ({geometry_plan.dimension}D)",
            "model_path": str(model_path),
            "geometry_plan": geometry_plan.to_dict(),
            "ui": ui,
        }

    # ===== Material =====

    def execute_define_globals(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Define global parameters with strict validation."""

        self._emit_step_start("参数/全局定义", "正在定义全局参数...")
        params = thought.get("parameters", {}) or step.parameters or {}
        raw_items = params.get("global_definitions")
        if not isinstance(raw_items, list):
            raw_items = getattr(plan, "global_definitions", []) or []

        parsed: list[GlobalDefinitionPlan] = []
        errors: list[Dict[str, Any]] = []
        seen_names = set()

        for idx, item in enumerate(raw_items, start=1):
            try:
                model = (
                    item
                    if isinstance(item, GlobalDefinitionPlan)
                    else GlobalDefinitionPlan.model_validate(item)
                )
            except Exception as e:
                errors.append(
                    {"index": idx, "field": "global_definitions", "message": f"格式错误: {e}"}
                )
                continue

            name = (model.name or "").strip()
            value = (model.value or "").strip()

            if not name:
                errors.append({"index": idx, "field": "name", "message": "参数名不能为空"})
                continue
            if not GLOBAL_NAME_RE.match(name):
                errors.append(
                    {
                        "index": idx,
                        "field": "name",
                        "message": "参数名不合法，必须满足 [A-Za-z_]\\w*",
                    }
                )
                continue
            lower = name.lower()
            if lower in seen_names:
                errors.append({"index": idx, "field": "name", "message": f"参数名重复: {name}"})
                continue
            seen_names.add(lower)

            if not value:
                errors.append({"index": idx, "field": "value", "message": f"{name} 的表达式不能为空"})
                continue

            parsed.append(model)

        if errors:
            return {
                "status": "error",
                "message": "全局定义校验失败，请先回到规划阶段澄清。",
                "error_code": "define_globals_validation_failed",
                "details": errors,
                "needs_planning_clarification": True,
            }

        if not parsed:
            plan.global_definitions = []
            self._emit_step_end("参数/全局定义", "未提供全局参数，已跳过", count=0)
            return {
                "status": "success",
                "message": "未提供全局参数，已跳过 define_globals",
                "global_definitions": [],
                "ui": {
                    "action": "跳过全局参数",
                    "detail": "当前计划未包含全局参数，无需写入 model.param()",
                    "target": "全局定义",
                },
            }

        plan.global_definitions = parsed

        # 会话级语义保存（双写之一）
        if self._context_manager and hasattr(self._context_manager, "load_plan"):
            try:
                current = self._context_manager.load_plan() or {}
                current["global_definitions"] = [g.model_dump() for g in parsed]
                self._context_manager.save_plan(current)
            except Exception as e:
                logger.warning("会话级全局定义写入失败: %s", e)

        if not plan.model_path:
            return {
                "status": "error",
                "message": "模型尚未创建，无法将全局定义写入 COMSOL param()。",
                "error_code": "model_not_ready_for_globals",
                "needs_planning_clarification": True,
            }

        controller = self._get_java_api_controller()
        save_to = self._stage_path(plan, "global")
        result = controller.define_global_parameters(
            plan.model_path,
            [g.model_dump() for g in parsed],
            save_to_path=save_to,
        )
        if result.get("status") == "error":
            return {
                "status": "error",
                "message": result.get("message", "写入全局参数失败"),
                "error_code": "define_globals_write_failed",
                "details": result.get("details", []),
                "needs_planning_clarification": True,
            }

        plan.model_path = result.get("saved_path") or plan.model_path
        self._update_latest(plan)
        if self._context_manager:
            self._context_manager.append_operation(
                "参数/全局定义",
                f"已写入 {len(parsed)} 个全局参数",
                "success",
                plan.model_path,
            )
        self._emit_step_end("参数/全局定义", "全局参数定义完成", count=len(parsed))
        return {
            "status": "success",
            "message": f"全局参数定义完成，共 {len(parsed)} 项",
            "global_definitions": [g.model_dump() for g in parsed],
            "saved_path": plan.model_path,
            "ui": {
                "action": "定义全局参数",
                "detail": f"写入 {len(parsed)} 个参数到 model.param()",
                "target": "全局定义",
            },
        }

    def execute_material(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行材料设置...")
        self._emit_step_start("材料设置", "正在添加材料...")

        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}

        material_plan = getattr(plan, "material_plan", None)
        if not material_plan:
            if not self._material_agent:
                self._material_agent = MaterialAgent()
            material_input = thought.get("parameters", {}).get("material_input") or plan.user_input
            material_plan = self._material_agent.parse(material_input)
            plan.material_plan = material_plan

        try:
            controller = self._get_java_api_controller()
            save_to = self._stage_path(plan, "material")
            result = controller.add_materials(
                plan.model_path, material_plan, save_to_path=save_to
            )
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "材料设置失败")}
            plan.model_path = result.get("saved_path") or plan.model_path
            self._update_latest(plan)
            if self._context_manager:
                self._context_manager.append_operation(
                    "材料设置", "材料设置成功", "success", plan.model_path
                )
            if self._event_bus:
                materials = getattr(material_plan, "materials", None) or getattr(
                    material_plan, "items", []
                )
                if hasattr(materials, "__iter__") and not isinstance(materials, dict):
                    mat_list = [
                        {
                            "material": getattr(m, "name", m) if hasattr(m, "name") else m,
                            "label": getattr(m, "label", str(m)),
                        }
                        for m in materials
                    ]
                else:
                    mat_list = []
                self._event_bus.emit_type(
                    EventType.MATERIAL_END, {"materials": mat_list, "message": "材料设置成功"}
                )
            ui = {
                "action": "分配材料属性",
                "detail": f"向模型中添加 {len(getattr(material_plan, 'materials', []))} 种材料并完成分配",
                "target": "材料: "
                + ", ".join(
                    [
                        getattr(m, "label", getattr(m, "name", "material"))
                        for m in (getattr(material_plan, "materials", []) or [])
                    ][:4]
                ),
            }
            return {
                "status": "success",
                "message": "材料设置成功",
                "material_plan": material_plan.to_dict(),
                "ui": ui,
            }
        except Exception as e:
            logger.error(f"材料设置失败: {e}")
            return {"status": "error", "message": f"材料设置失败: {e}"}

    def execute_update_material_property(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """仅更新已有材料属性（k / E / nu 等），用于修复求解缺材料属性错误。"""
        logger.info("执行更新材料属性...")
        self._emit_step_start("更新材料属性", "正在为已有材料补充属性（如 k / E / nu）...")

        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}

        params = thought.get("parameters", {}) or step.parameters or {}
        properties = dict(params.get("properties") or {})
        if not properties:
            if params.get("nu") is not None or params.get("E") is not None:
                from agent.executor.java_api_controller import (
                    DEFAULT_POISSONS_RATIO,
                    DEFAULT_YOUNGS_MODULUS_SOLID,
                )

                properties = {
                    "E": params.get("E", DEFAULT_YOUNGS_MODULUS_SOLID),
                    "nu": params.get("nu", DEFAULT_POISSONS_RATIO),
                }
            else:
                properties = {"k": params.get("k", DEFAULT_THERMAL_K_SOLID)}
        property_group = (params.get("property_group") or "Def").strip() or "Def"

        material_names = list(params.get("material_names") or [])
        if params.get("material_name") and not material_names:
            material_names = [params["material_name"]]
        if not material_names and getattr(plan, "material_plan", None):
            materials = getattr(plan.material_plan, "materials", None) or []
            material_names = [getattr(m, "name", None) or getattr(m, "label", "") for m in materials if getattr(m, "name", None) or getattr(m, "label", "")]
        if not material_names:
            controller = self._get_java_api_controller()
            res = controller.list_material_names(plan.model_path)
            if res.get("status") == "success" and res.get("names"):
                material_names = res["names"]
        if not material_names:
            return {"status": "error", "message": "未找到可更新的材料节点，请先添加材料或指定 material_name / material_names"}

        controller = self._get_java_api_controller()
        updated = []
        for name in material_names:
            if not name:
                continue
            result = controller.update_material_properties(
                plan.model_path, name, properties, property_group
            )
            if result.get("status") == "success":
                updated.append(name)
            else:
                logger.warning("更新材料 %s 属性失败: %s", name, result.get("message"))

        if not updated:
            return {"status": "error", "message": "所有材料属性更新均失败"}

        self._update_latest(plan)
        if self._context_manager:
            self._context_manager.append_operation(
                "更新材料属性", f"已为 {len(updated)} 个材料补充属性", "success", plan.model_path
            )
        if self._event_bus:
            self._event_bus.emit_type(
                EventType.MATERIAL_END,
                {"materials": [{"material": n} for n in updated], "message": "材料属性已更新"},
            )
        ui = {
            "action": "更新材料属性",
            "detail": f"为材料 {', '.join(updated[:4])}{'...' if len(updated) > 4 else ''} 补充属性 {list(properties.keys())}",
            "target": "材料: " + ", ".join(updated[:4]),
        }
        return {
            "status": "success",
            "message": f"已更新 {len(updated)} 个材料的属性",
            "updated": updated,
            "properties": properties,
            "ui": ui,
        }

    # ===== Physics =====

    def execute_physics(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行物理场设置...")
        self._emit_step_start("物理场", "正在添加物理场...")

        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}

        if not self._physics_agent:
            self._physics_agent = PhysicsAgent()

        physics_input = thought.get("parameters", {}).get("physics_input", plan.user_input)

        try:
            physics_plan = getattr(plan, "physics_plan", None)
            if not physics_plan:
                physics_plan = self._physics_agent.parse(physics_input)
                plan.physics_plan = physics_plan
            controller = self._get_java_api_controller()
            save_to = self._stage_path(plan, "physics")
            result = controller.add_physics(
                plan.model_path, physics_plan, save_to_path=save_to
            )
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "物理场设置失败")}
            plan.model_path = result.get("saved_path") or plan.model_path
            self._update_latest(plan)
            if self._context_manager:
                self._context_manager.append_operation(
                    "物理场", "物理场设置成功", "success", plan.model_path
                )
            if self._event_bus:
                self._event_bus.emit_type(
                    EventType.COUPLING_ADDED,
                    {"message": "物理场设置成功", "type": "physics"},
                )
            ui = {
                "action": "添加物理场与边界条件",
                "detail": "根据物理计划添加物理接口、边界与域条件",
                "target": "物理场: "
                + ", ".join(
                    [getattr(f, "type", "physics") for f in getattr(physics_plan, "fields", [])][:4]
                ),
            }
            return {
                "status": "success",
                "message": "物理场设置成功",
                "physics_plan": physics_plan.model_dump()
                if hasattr(physics_plan, "model_dump")
                else physics_plan,
                "ui": ui,
            }
        except NotImplementedError:
            logger.warning("PhysicsAgent 尚未实现，跳过物理场设置")
            return {"status": "warning", "message": "物理场设置功能尚未实现"}
        except Exception as e:
            logger.error(f"物理场设置失败: {e}")
            return {"status": "error", "message": f"物理场设置失败: {e}"}

    # ===== Mesh =====

    def execute_mesh(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行网格划分...")
        self._emit_step_start("网格划分", "正在生成网格...")

        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}

        try:
            mesh_params = thought.get("parameters", {}).get("mesh", {})
            controller = self._get_java_api_controller()
            save_to = self._stage_path(plan, "mesh")
            result = controller.generate_mesh(
                plan.model_path, mesh_params, save_to_path=save_to
            )
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "网格划分失败")}
            plan.model_path = result.get("saved_path") or plan.model_path
            self._update_latest(plan)
            if self._context_manager:
                self._context_manager.append_operation(
                    "网格划分", "网格划分成功", "success", plan.model_path
                )
            self._emit_step_end("网格划分", "网格划分成功", mesh_info=result)
            ui = {
                "action": "生成网格",
                "detail": "在几何上生成默认网格序列 mesh1",
                "target": "网格: mesh1",
            }
            return {"status": "success", "message": "网格划分成功", "mesh_info": result, "ui": ui}
        except Exception as e:
            logger.error(f"网格划分失败: {e}")
            return {"status": "error", "message": f"网格划分失败: {e}"}

    # ===== Study =====

    def execute_study(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行研究配置...")
        self._emit_step_start("研究配置", "正在配置研究...")

        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}

        if not self._study_agent:
            self._study_agent = StudyAgent()

        study_input = thought.get("parameters", {}).get("study_input", plan.user_input)

        try:
            study_plan = getattr(plan, "study_plan", None)
            if not study_plan:
                study_plan = self._study_agent.parse(study_input)
                plan.study_plan = study_plan
            controller = self._get_java_api_controller()
            save_to = self._stage_path(plan, "study")
            result = controller.configure_study(
                plan.model_path, study_plan, save_to_path=save_to
            )
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "研究配置失败")}
            plan.model_path = result.get("saved_path") or plan.model_path
            self._update_latest(plan)
            if self._context_manager:
                self._context_manager.append_operation(
                    "研究配置", "研究配置成功", "success", plan.model_path
                )
            self._emit_step_end(
                "研究配置",
                "研究配置成功",
                study_plan=study_plan.model_dump()
                if hasattr(study_plan, "model_dump")
                else study_plan,
            )
            ui = {
                "action": "配置研究与求解设置",
                "detail": "根据研究计划创建研究节点并设置稳态/瞬态等求解步骤",
                "target": "研究: "
                + ", ".join(
                    [getattr(s, "type", "study") for s in getattr(study_plan, "studies", [])][:4]
                ),
            }
            return {
                "status": "success",
                "message": "研究配置成功",
                "study_plan": study_plan.model_dump()
                if hasattr(study_plan, "model_dump")
                else study_plan,
                "ui": ui,
            }
        except NotImplementedError:
            logger.warning("StudyAgent 尚未实现，跳过研究配置")
            return {"status": "warning", "message": "研究配置功能尚未实现"}
        except Exception as e:
            logger.error(f"研究配置失败: {e}")
            return {"status": "error", "message": f"研究配置失败: {e}"}

    # ===== Solve =====

    def execute_solve(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行求解...")
        self._emit_step_start("求解", "正在求解...")

        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在"}

        def _on_solve_progress(payload: Dict[str, Any]) -> None:
            if not self._event_bus:
                return
            data = dict(payload or {})
            compute = data.pop("compute", None)
            try:
                if compute:
                    self._event_bus.emit_type(EventType.COMPUTE_BACKEND, compute)
                self._event_bus.emit_type(EventType.SOLVE_PROGRESS, data)
            except Exception:
                pass

        try:
            from agent.executor.compute_backend import detect_compute_backend

            if self._event_bus:
                self._event_bus.emit_type(
                    EventType.COMPUTE_BACKEND, detect_compute_backend().to_dict()
                )
                self._event_bus.emit_type(
                    EventType.SOLVE_PROGRESS,
                    {
                        "phase": "prepare",
                        "percent": 0,
                        "message": "准备求解…",
                        "active": True,
                    },
                )

            controller = self._get_java_api_controller()
            save_to = self._stage_path(plan, "solve")
            result = controller.solve(
                plan.model_path,
                save_to_path=save_to,
                progress_callback=_on_solve_progress,
            )
            if result.get("status") == "error":
                msg = result.get("message", "求解失败")
                return {"status": "error", "message": msg}
            plan.model_path = result.get("saved_path") or plan.model_path
            cleanup = self.cleanup_stage_models(plan)
            model_path = plan.model_path
            # 可选：用 MPh 做求解后物理量轻量验收（不阻断主成功路径）
            verify = None
            try:
                from agent.executor import mph_backend

                params = thought.get("parameters", {}) or step.parameters or {}
                if mph_backend.should_use_mph() and model_path:
                    exprs = params.get("verify_expressions") or params.get("expressions")
                    if isinstance(exprs, str):
                        exprs = [exprs]
                    verify = mph_backend.verify_after_solve(
                        model_path,
                        expressions=list(exprs) if exprs else None,
                    )
            except Exception as ve:
                logger.debug("MPh 求解验收跳过: %s", ve)
            success_msg = f"求解成功。模型位置：{model_path}" if model_path else "求解成功"
            if self._context_manager:
                self._context_manager.append_operation(
                    "求解", success_msg, "success", model_path
                )
            self._emit_step_end(
                "求解",
                success_msg,
                solve_info=result,
                model_path=model_path,
                cleaned_stage_models=cleanup.get("removed") or [],
            )
            ui = {
                "action": "求解模型",
                "detail": f"求解成功，模型已保存：{model_path}" if model_path else "运行研究序列并求解模型",
                "target": model_path or "研究: 自动选择第一个研究节点",
            }
            out: Dict[str, Any] = {
                "status": "success",
                "message": success_msg,
                "model_path": model_path,
                "saved_path": model_path,
                "solve_info": result,
                "ui": ui,
            }
            if verify:
                out["mph_verify"] = verify
            return out
        except Exception as e:
            logger.error(f"求解失败: {e}")
            if self._event_bus:
                try:
                    self._event_bus.emit_type(
                        EventType.SOLVE_PROGRESS,
                        {
                            "phase": "error",
                            "percent": 0,
                            "message": f"求解失败: {e}",
                            "active": False,
                        },
                    )
                except Exception:
                    pass
            return {"status": "error", "message": f"求解失败: {e}"}

    # ===== Geometry IO / Selection / Postprocess =====

    def execute_import_geometry(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """导入几何文件（STEP/IGES/STL 等）。"""
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}
        params = thought.get("parameters", {}) or step.parameters
        file_path = params.get("file_path") or params.get("path")
        if not file_path:
            return {"status": "error", "message": "缺少 file_path 参数"}
        self._emit_step_start("几何导入", "正在导入几何文件...")
        controller = self._get_java_api_controller()
        result = controller.import_geometry(
            plan.model_path,
            file_path,
            geom_tag=params.get("geom_tag", "geom1"),
            feature_tag=params.get("feature_tag"),
        )
        if result.get("status") == "error":
            return result
        if result.get("saved_path"):
            plan.model_path = result["saved_path"]
        self._emit_step_end("几何导入", result.get("message", "几何导入成功"), path=file_path)
        return {
            "status": "success",
            "message": result.get("message", "几何导入成功"),
            "path": file_path,
        }

    def execute_create_selection(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """创建选择集。"""
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}
        params = thought.get("parameters", {}) or step.parameters
        tag = params.get("tag") or params.get("selection_tag", "sel1")
        self._emit_step_start("选择集", f"正在创建选择集 {tag}...")
        controller = self._get_java_api_controller()
        result = controller.create_selection(
            plan.model_path,
            tag=tag,
            kind=params.get("kind", "Explicit"),
            geom_tag=params.get("geom_tag", "geom1"),
            entity_dim=params.get("entity_dim"),
            entities=params.get("entities"),
            all=params.get("all"),
        )
        if result.get("status") == "error":
            return result
        self._emit_step_end("选择集", result.get("message", "选择集创建成功"), tag=tag)
        return {"status": "success", "message": result.get("message"), "tag": tag}

    def execute_export_results(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """导出结果图或数据。CSV/数据优先尝试可选 MPh 后端，失败再回退 Java API。"""
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在"}
        params = thought.get("parameters", {}) or step.parameters
        out_path = params.get("out_path") or params.get("output_path") or params.get("path")
        if not out_path:
            return {"status": "error", "message": "缺少 out_path 参数"}
        self._emit_step_start("结果导出", "正在导出结果...")
        export_type = (params.get("export_type") or "image").lower()
        prefer_mph = str(params.get("backend") or "").lower() in ("mph", "auto")
        is_data_export = (
            export_type in ("data", "csv", "table", "numeric")
            or bool(params.get("dataset"))
            or bool(params.get("table_tag"))
            or str(out_path).lower().endswith(".csv")
        )

        if is_data_export or prefer_mph:
            try:
                from agent.executor import mph_backend

                force = True if str(params.get("backend") or "").lower() == "mph" else None
                if mph_backend.should_use_mph(force=force):
                    mph_result = mph_backend.export_data(
                        plan.model_path,
                        out_path,
                        node=params.get("node") or params.get("export_node"),
                        dataset=params.get("dataset") or params.get("table_tag"),
                    )
                    if mph_result.get("status") == "success":
                        self._emit_step_end(
                            "结果导出",
                            mph_result.get("message", "MPh 导出成功"),
                            path=out_path,
                            backend="mph",
                        )
                        return {
                            "status": "success",
                            "message": mph_result.get("message"),
                            "path": out_path,
                            "backend": "mph",
                        }
                    logger.info("MPh 导出未成功，回退 Java API: %s", mph_result.get("message"))
            except Exception as e:
                logger.info("MPh 导出跳过，回退 Java API: %s", e)

        if export_type == "data" or params.get("dataset"):
            controller = self._get_java_api_controller()
            result = controller.export_data(
                plan.model_path,
                params.get("dataset") or params.get("plot_group_tag", "dset1"),
                out_path,
                export_type=params.get("data_type", "Data"),
                **{
                    k: v
                    for k, v in params.items()
                    if k
                    not in (
                        "out_path",
                        "output_path",
                        "path",
                        "export_type",
                        "dataset",
                        "plot_group_tag",
                        "data_type",
                        "backend",
                        "node",
                        "export_node",
                        "table_tag",
                    )
                },
            )
        elif params.get("table_tag"):
            controller = self._get_java_api_controller()
            result = controller.table_export(plan.model_path, params["table_tag"], out_path)
        else:
            controller = self._get_java_api_controller()
            result = controller.export_plot_image(
                plan.model_path,
                params.get("plot_group_tag", "pg1"),
                out_path,
                width=params.get("width", 800),
                height=params.get("height", 600),
                **{
                    k: v
                    for k, v in params.items()
                    if k
                    not in (
                        "out_path",
                        "output_path",
                        "path",
                        "plot_group_tag",
                        "width",
                        "height",
                        "backend",
                    )
                },
            )
        if result.get("status") == "error":
            return result
        self._emit_step_end(
            "结果导出",
            result.get("message", "导出成功"),
            path=out_path,
            backend="java_api",
        )
        return {
            "status": "success",
            "message": result.get("message"),
            "path": out_path,
            "backend": "java_api",
        }

    def execute_evaluate_results(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """对已求解模型做表达式求值（优先 MPh）。"""
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在"}
        params = thought.get("parameters", {}) or step.parameters or {}
        expression = (
            params.get("expression")
            or params.get("expr")
            or params.get("quantity")
            or ""
        )
        self._emit_step_start("结果求值", f"求值: {expression or '(默认验收表达式)'}...")
        try:
            from agent.executor import mph_backend

            if not mph_backend.should_use_mph(
                force=True if str(params.get("backend") or "").lower() == "mph" else None
            ):
                return {
                    "status": "error",
                    "message": "未启用/未安装 MPh。请执行 uv sync --extra mph，并设置 MPH_BACKEND=auto",
                }
            if expression:
                result = mph_backend.evaluate(
                    plan.model_path,
                    str(expression),
                    dataset=params.get("dataset"),
                    unit=params.get("unit"),
                )
            else:
                exprs = params.get("expressions")
                if isinstance(exprs, str):
                    exprs = [exprs]
                result = mph_backend.verify_after_solve(
                    plan.model_path,
                    expressions=list(exprs) if exprs else None,
                )
            if result.get("status") == "error":
                return result
            self._emit_step_end(
                "结果求值",
                result.get("message", "求值完成"),
                backend="mph",
                value=result.get("value"),
            )
            return {
                "status": "success" if result.get("status") != "warning" else "warning",
                "message": result.get("message"),
                "value": result.get("value"),
                "backend": "mph",
                "result": result,
            }
        except Exception as e:
            logger.error("evaluate_results 失败: %s", e)
            return {"status": "error", "message": f"evaluate_results 失败: {e}"}

    def execute_set_parameters(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """批量写入全局参数（优先 MPh，便于参数化扫描改参）。"""
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在"}
        params = thought.get("parameters", {}) or step.parameters or {}
        mapping = params.get("parameters") or params.get("values") or params.get("map")
        if not isinstance(mapping, dict) or not mapping:
            return {
                "status": "error",
                "message": "set_parameters 需要 parameters 字典，例如 {\"t_fin\": \"0.002[m]\"}",
            }
        self._emit_step_start("参数设置", f"写入 {len(mapping)} 个全局参数...")
        try:
            from agent.executor import mph_backend

            if not mph_backend.should_use_mph(
                force=True if str(params.get("backend") or "").lower() == "mph" else None
            ):
                return {
                    "status": "error",
                    "message": "未启用/未安装 MPh。请执行 uv sync --extra mph",
                }
            save_to = params.get("save_path") or self._stage_path(plan, "latest")
            result = mph_backend.set_parameters(
                plan.model_path, dict(mapping), save_path=save_to
            )
            if result.get("status") == "error":
                return result
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
                self._update_latest(plan)
            self._emit_step_end(
                "参数设置",
                result.get("message", "参数已更新"),
                backend="mph",
            )
            return {
                "status": "success",
                "message": result.get("message"),
                "parameters": result.get("parameters"),
                "backend": "mph",
            }
        except Exception as e:
            logger.error("set_parameters 失败: %s", e)
            return {"status": "error", "message": f"set_parameters 失败: {e}"}

    # ===== Official Java API 调用（高级）=====

    def execute_call_official_api(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        调用已集成的 COMSOL 官方 Java API。
        两种用法：
        - 直接指定 Java 方法名：method + args + target_path → invoke_official_api
        - 指定包装函数名：wrapper 或 wrapper_name → 调用 JavaAPIController 上的 api_* 包装方法
        """
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在"}
        params = thought.get("parameters", {}) or step.parameters or {}
        method = params.get("method")
        wrapper = params.get("wrapper") or params.get("wrapper_name")
        args = params.get("args")
        target_path = params.get("target_path")

        if method is not None and not isinstance(method, str):
            return {"status": "error", "message": "method 参数必须为字符串"}
        if isinstance(method, str):
            method = method.strip()
            if not method:
                return {"status": "error", "message": "method 参数不能为空字符串"}

        if not method and not wrapper:
            return {
                "status": "error",
                "message": "call_official_api 需要提供 method 或 wrapper 参数",
            }

        label = wrapper or method
        self._emit_step_start("Java API", f"调用 COMSOL Java API: {label} ...")

        try:
            if wrapper:
                # 调用静态生成的 api_* 包装函数
                controller = self._get_java_api_controller()
                func = getattr(controller, wrapper, None)
                if not func:
                    return {"status": "error", "message": f"未找到官方 API 包装函数: {wrapper}"}
                result = func(model_path=plan.model_path, args=args, target_path=target_path)
            else:
                # 直接按 method + target_path 调用
                controller = self._get_java_api_controller()
                if method is None:
                    return {"status": "error", "message": "method 参数缺失"}
                safe_method_name: str = method
                result = controller.invoke_official_api(
                    model_path=plan.model_path,
                    method_name=safe_method_name,
                    args=args,
                    target_path=target_path,
                )
            if result.get("status") == "error":
                return result
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
            self._emit_step_end(
                "Java API", result.get("message", "Java API 调用成功"), method=label
            )
            return {
                "status": "success",
                "message": result.get("message", "Java API 调用成功"),
                "result": result,
            }
        except Exception as e:
            logger.error("call_official_api 失败: %s", e)
            return {"status": "error", "message": f"call_official_api 失败: {e}"}

    # ===== Retry / Skip =====

    def execute_retry(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        failed_steps = thought.get("parameters", {}).get("failed_steps", [])
        if not failed_steps:
            return {"status": "error", "message": "没有需要重试的步骤"}
        for step_id in failed_steps:
            for s in plan.execution_path:
                if s.step_id == step_id and s.status == "failed":
                    s.status = "pending"
                    logger.info(f"重置步骤 {step_id} 状态为 pending")
                    break
        return {"status": "success", "message": f"已重置 {len(failed_steps)} 个失败步骤"}

    def execute_skip(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        failed_steps = thought.get("parameters", {}).get("failed_steps", [])
        if not failed_steps:
            return {"status": "error", "message": "没有需要跳过的步骤"}
        for step_id in failed_steps:
            for s in plan.execution_path:
                if s.step_id == step_id:
                    s.status = "skipped"
                    logger.info(f"跳过步骤 {step_id}")
                    break
        return {"status": "success", "message": f"已跳过 {len(failed_steps)} 个失败步骤"}
