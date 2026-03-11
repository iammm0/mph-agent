"""行动执行器 — 支持材料、3D 几何"""
from typing import Dict, Any, Optional
from pathlib import Path

from agent.planner.geometry_agent import GeometryAgent
from agent.planner.physics_agent import PhysicsAgent
from agent.planner.material_agent import MaterialAgent
from agent.planner.study_agent import StudyAgent
from agent.executor.comsol_runner import COMSOLRunner
from agent.executor.java_api_controller import JavaAPIController
from agent.utils.logger import get_logger
from agent.utils.config import get_settings
from agent.core.events import EventType
from schemas.task import ReActTaskPlan, ExecutionStep

logger = get_logger(__name__)


class ActionExecutor:
    """行动执行器 - 执行具体的建模操作"""

    def __init__(self, event_bus: Optional[Any] = None, context_manager: Optional[Any] = None):
        self.settings = get_settings()
        self.comsol_runner = COMSOLRunner()
        self.java_api_controller = JavaAPIController()
        self._event_bus = event_bus
        self._context_manager = context_manager

        self._geometry_agent = None
        self._physics_agent = None
        self._material_agent = None
        self._study_agent = None

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

        action_handlers = {
            "create_geometry": self.execute_geometry,
            "add_material": self.execute_material,
            "add_physics": self.execute_physics,
            "generate_mesh": self.execute_mesh,
            "configure_study": self.execute_study,
            "solve": self.execute_solve,
            "import_geometry": self.execute_import_geometry,
            "create_selection": self.execute_create_selection,
            "export_results": self.execute_export_results,
            "call_official_api": self.execute_call_official_api,
            "retry": self.execute_retry,
            "skip": self.execute_skip,
        }

        handler = action_handlers.get(step.action)
        if not handler:
            return {"status": "error", "message": f"未知的行动: {step.action}"}

        try:
            return handler(plan, step, thought)
        except Exception as e:
            logger.error(f"执行步骤失败: {e}")
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
        model_name = getattr(plan, "model_name", None) or "model"
        output_filename = f"{model_name}.mph"

        output_dir = getattr(plan, "output_dir", None)
        out_path = Path(output_dir) if output_dir else None
        try:
            if out_path is not None:
                model_path = self.comsol_runner.create_model_from_plan(geometry_plan, output_filename, output_dir=out_path)
            else:
                model_path = self.comsol_runner.create_model_from_plan(geometry_plan, output_filename)
        except Exception as e:
            logger.error(f"几何建模失败: {e}")
            return {"status": "error", "message": f"几何建模失败: {e}"}
        plan.model_path = str(model_path)
        if self._context_manager:
            self._context_manager.append_operation("几何建模", f"几何建模成功 ({geometry_plan.dimension}D)", "success", str(model_path))
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
            material_input = (
                thought.get("parameters", {}).get("material_input")
                or plan.user_input
            )
            material_plan = self._material_agent.parse(material_input)
            plan.material_plan = material_plan

        try:
            result = self.java_api_controller.add_materials(plan.model_path, material_plan)
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "材料设置失败")}
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
            if self._context_manager:
                self._context_manager.append_operation("材料设置", "材料设置成功", "success", plan.model_path)
            if self._event_bus:
                materials = getattr(material_plan, "materials", None) or getattr(material_plan, "items", [])
                if hasattr(materials, "__iter__") and not isinstance(materials, dict):
                    mat_list = [{"material": getattr(m, "name", m) if hasattr(m, "name") else m, "label": getattr(m, "label", str(m))} for m in materials]
                else:
                    mat_list = []
                self._event_bus.emit_type(EventType.MATERIAL_END, {"materials": mat_list, "message": "材料设置成功"})
            ui = {
                "action": "分配材料属性",
                "detail": f"向模型中添加 {len(getattr(material_plan, 'materials', []))} 种材料并完成分配",
                "target": "材料: " + ", ".join(
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
            result = self.java_api_controller.add_physics(plan.model_path, physics_plan)
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "物理场设置失败")}
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
            if self._context_manager:
                self._context_manager.append_operation("物理场", "物理场设置成功", "success", plan.model_path)
            if self._event_bus:
                self._event_bus.emit_type(
                    EventType.COUPLING_ADDED,
                    {"message": "物理场设置成功", "type": "physics"},
                )
            ui = {
                "action": "添加物理场与边界条件",
                "detail": "根据物理计划添加物理接口、边界与域条件",
                "target": "物理场: " + ", ".join(
                    [getattr(f, "type", "physics") for f in getattr(physics_plan, "fields", [])][:4]
                ),
            }
            return {
                "status": "success",
                "message": "物理场设置成功",
                "physics_plan": physics_plan.model_dump() if hasattr(physics_plan, "model_dump") else physics_plan,
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
            result = self.java_api_controller.generate_mesh(plan.model_path, mesh_params)
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "网格划分失败")}
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
            if self._context_manager:
                self._context_manager.append_operation("网格划分", "网格划分成功", "success", plan.model_path)
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
            result = self.java_api_controller.configure_study(plan.model_path, study_plan)
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "研究配置失败")}
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
            if self._context_manager:
                self._context_manager.append_operation("研究配置", "研究配置成功", "success", plan.model_path)
            self._emit_step_end("研究配置", "研究配置成功", study_plan=study_plan.model_dump() if hasattr(study_plan, "model_dump") else study_plan)
            ui = {
                "action": "配置研究与求解设置",
                "detail": "根据研究计划创建研究节点并设置稳态/瞬态等求解步骤",
                "target": "研究: " + ", ".join(
                    [getattr(s, "type", "study") for s in getattr(study_plan, "studies", [])][:4]
                ),
            }
            return {
                "status": "success",
                "message": "研究配置成功",
                "study_plan": study_plan.model_dump() if hasattr(study_plan, "model_dump") else study_plan,
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

        try:
            result = self.java_api_controller.solve(plan.model_path)
            if result.get("status") == "error":
                # 求解失败：此时 model_path 仍然指向求解前的模型，前端可据此查看“部分生成”的模型。
                msg = result.get("message", "求解失败")
                return {"status": "error", "message": msg}
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
            if self._context_manager:
                self._context_manager.append_operation("求解", "求解成功", "success", plan.model_path)
            self._emit_step_end("求解", "求解成功", solve_info=result)
            ui = {
                "action": "求解模型",
                "detail": "运行研究序列并求解模型",
                "target": "研究: 自动选择第一个研究节点",
            }
            return {"status": "success", "message": "求解成功", "solve_info": result, "ui": ui}
        except Exception as e:
            logger.error(f"求解失败: {e}")
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
        result = self.java_api_controller.import_geometry(
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
        return {"status": "success", "message": result.get("message", "几何导入成功"), "path": file_path}

    def execute_create_selection(
        self, plan: ReActTaskPlan, step: ExecutionStep, thought: Dict[str, Any]
    ) -> Dict[str, Any]:
        """创建选择集。"""
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在，请先执行几何建模"}
        params = thought.get("parameters", {}) or step.parameters
        tag = params.get("tag") or params.get("selection_tag", "sel1")
        self._emit_step_start("选择集", f"正在创建选择集 {tag}...")
        result = self.java_api_controller.create_selection(
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
        """导出结果图或数据。"""
        if not plan.model_path:
            return {"status": "error", "message": "模型文件不存在"}
        params = thought.get("parameters", {}) or step.parameters
        out_path = params.get("out_path") or params.get("output_path") or params.get("path")
        if not out_path:
            return {"status": "error", "message": "缺少 out_path 参数"}
        self._emit_step_start("结果导出", "正在导出结果...")
        export_type = (params.get("export_type") or "image").lower()
        if export_type == "data" or params.get("dataset"):
            result = self.java_api_controller.export_data(
                plan.model_path,
                params.get("dataset") or params.get("plot_group_tag", "dset1"),
                out_path,
                export_type=params.get("data_type", "Data"),
                **{k: v for k, v in params.items() if k not in ("out_path", "output_path", "path", "export_type", "dataset", "plot_group_tag", "data_type")},
            )
        elif params.get("table_tag"):
            result = self.java_api_controller.table_export(
                plan.model_path, params["table_tag"], out_path
            )
        else:
            result = self.java_api_controller.export_plot_image(
                plan.model_path,
                params.get("plot_group_tag", "pg1"),
                out_path,
                width=params.get("width", 800),
                height=params.get("height", 600),
                **{k: v for k, v in params.items() if k not in ("out_path", "output_path", "path", "plot_group_tag", "width", "height")},
            )
        if result.get("status") == "error":
            return result
        self._emit_step_end("结果导出", result.get("message", "导出成功"), path=out_path)
        return {"status": "success", "message": result.get("message"), "path": out_path}

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

        if not method and not wrapper:
            return {"status": "error", "message": "call_official_api 需要提供 method 或 wrapper 参数"}

        label = wrapper or method
        self._emit_step_start("Java API", f"调用 COMSOL Java API: {label} ...")

        try:
            if wrapper:
                # 调用静态生成的 api_* 包装函数
                func = getattr(self.java_api_controller, wrapper, None)
                if not func:
                    return {"status": "error", "message": f"未找到官方 API 包装函数: {wrapper}"}
                result = func(model_path=plan.model_path, args=args, target_path=target_path)
            else:
                # 直接按 method + target_path 调用
                result = self.java_api_controller.invoke_official_api(
                    model_path=plan.model_path,
                    method_name=method,
                    args=args,
                    target_path=target_path,
                )
            if result.get("status") == "error":
                return result
            if result.get("saved_path"):
                plan.model_path = result["saved_path"]
            self._emit_step_end("Java API", result.get("message", "Java API 调用成功"), method=label)
            return {"status": "success", "message": result.get("message", "Java API 调用成功"), "result": result}
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
                    s.status = "completed"
                    logger.info(f"跳过步骤 {step_id}")
                    break
        return {"status": "success", "message": f"已跳过 {len(failed_steps)} 个失败步骤"}
