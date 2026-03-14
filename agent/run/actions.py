"""无 Typer 依赖的纯函数：供 TUI 与 CLI 子命令共用的 do_run、do_plan、do_exec 等。"""
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.core.dependencies import get_agent, get_context_manager, get_settings
from agent.core.events import EventBus
from agent.executor.comsol_runner import COMSOLRunner
from agent.executor.java_api_controller import JavaAPIController
from agent.memory import update_conversation_memory, update_conversation_memory_async
from agent.utils.env_check import check_environment
from agent.utils.logger import setup_logging, get_logger
from schemas.geometry import GeometryPlan
from schemas.task import ClarifyingAnswer
from agent.react.exceptions import PlanNeedsClarification, ReActNeedsReorchestrate

logger = get_logger(__name__)

# 与桌面端新会话快捷提示词一致，用于 /demo，与 COMSOL 案例库风格类似：偏 3D、多物理场、包含求解与结果导出。
QUICK_TEST_PROMPTS = [
    # 3D 热-结构（热应力）
    "构建一个 3D 铝合金支架热-结构耦合模型：几何为 0.2 m × 0.1 m × 0.05 m 的带两个圆孔支架，材料采用铝合金（给出 E、nu、density 等）；添加固体传热和固体力学，并通过 Thermal Expansion 建立热应力耦合；底面固定且温度 293.15 K，顶面对流换热（h=10 W/(m^2*K)，环境 293.15 K），一侧面施加恒定热通量 5000 W/m^2；生成适中网格，做稳态研究并求解，最后导出温度场云图和等效应力云图到 output/brace_T3D.png 与 output/brace_sigma3D.png。",
    # 3D 流体-传热（内部冷却）
    "创建一个 3D 管道内部强制对流换热模型：长度 1 m、内径 0.02 m 的圆柱形流道，外部包覆 0.005 m 厚固体壁；流体为水，固体壁为钢或铜；在流体域添加层流流动与流体中的热传导，在固体壁添加固体传热；入口速度 0.5 m/s、温度 293.15 K，出口压力 0 Pa，外壁恒温 353.15 K；生成包含边界层的网格，配置稳态共轭传热研究并求解，导出流体温度场图像到 output/pipe_ctf_T3D.png。",
    # 3D 电磁-传热（线圈发热）
    "构建一个 3D 铜线圈电磁-热耦合模型：若干匝环形铜线圈包围一个钢制工件，外部为空气域；线圈用铜、工件用钢、空气域为空气；在铜线圈和工件区域添加电磁场物理并施加交流电流或电压，使线圈和工件中产生电阻/涡流发热；将电磁发热作为热源耦合到固体传热中，外表面与环境之间采用对流或恒温边界；生成适合 3D 电磁-热问题的网格，做稳态或频域-稳态耦合求解，导出工件温度场云图到 output/coil_heat_T3D.png。",
    # 3D 参数化传热（散热器）
    "构建一个 3D 散热器稳态传热参数化扫描模型：基板 0.1 m × 0.1 m × 0.01 m，上方布置多排散热片（高度约 0.03 m，厚度和间距作为参数）；材料为铝；基板底面施加热通量 10000 W/m^2，上表面与散热片外表面对流换热（h=20 W/(m^2*K)，环境 293.15 K）；添加固体传热，生成适中网格，配置稳态研究并添加参数化扫描（例如按散热片厚度/间距扫描 3~5 个取值）；求解完成后，将每个工况下的最大温度或平均温度导出到 CSV 文件 output/heatsink_parametric.csv。",
]


def _update_memory_after_run(
    conversation_id: Optional[str],
    user_input: str,
    assistant_summary: str,
    success: bool,
) -> None:
    """有 conversation_id 时异步更新会话记忆（本地异步 IO，无 Redis/Celery）。"""
    if not conversation_id:
        return
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(
                update_conversation_memory_async(
                    conversation_id, user_input, assistant_summary, success
                )
            )
        else:
            asyncio.run(
                update_conversation_memory_async(
                    conversation_id, user_input, assistant_summary, success
                )
            )
    except Exception:
        update_conversation_memory(
            conversation_id, user_input, assistant_summary, success
        )


def _ensure_logging(verbose: bool = False) -> None:
    setup_logging("DEBUG" if verbose else "INFO")


def do_run(
    user_input: str,
    output: Optional[str] = None,
    use_react: bool = True,
    no_context: bool = False,
    conversation_id: Optional[str] = None,
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    ollama_url: Optional[str] = None,
    model: Optional[str] = None,
    max_iterations: int = 10,
    skip_check: bool = False,
    verbose: bool = False,
    event_bus: Optional[EventBus] = None,
    clarifying_answers: Optional[list[dict[str, Any]]] = None,
    given_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, bool]:
    """执行默认模式：自然语言 -> 创建模型。given_plan 非空时（Plan 模式进入）直接使用该计划，跳过编排。"""
    _ensure_logging(verbose)
    from agent.utils.env_check import validate_environment

    if not skip_check:
        is_valid, error_msg = validate_environment()
        if not is_valid:
            return False, f"环境检查未通过: {error_msg}", False

    context_manager = get_context_manager(conversation_id)
    memory_context = None if no_context else context_manager.get_context_for_planner()
    try:
        if use_react:
            output_dir = context_manager.context_dir if conversation_id else None
            if conversation_id:
                context_manager.start_run_log(user_input)
            core = get_agent(
                "core",
                backend=backend,
                api_key=api_key,
                base_url=base_url,
                ollama_url=ollama_url,
                model=model,
                max_iterations=max_iterations,
                event_bus=event_bus,
                context_manager=context_manager if conversation_id else None,
            )

            # 将前端传来的 clarifying_answers dict 列表转换为 Pydantic 模型列表
            clarifying_models: Optional[list[ClarifyingAnswer]] = None
            if clarifying_answers:
                clarifying_models = []
                for item in clarifying_answers:
                    try:
                        clarifying_models.append(ClarifyingAnswer.model_validate(item))
                    except Exception:
                        continue

            try:
                model_path = core.run(
                    user_input,
                    output,
                    memory_context=memory_context,
                    output_dir=output_dir,
                    clarifying_answers=clarifying_models,
                    given_plan=given_plan,
                )
            except PlanNeedsClarification as e:
                # 计划已生成但需要澄清问题：视为成功，交由前端展示 PLAN_END 事件与问题列表
                logger.info("Plan 阶段已完成，等待澄清问题回答: %s", e)
                context_manager.add_conversation(
                    user_input=user_input,
                    plan={"architecture": "react", "status": "plan_needs_clarification"},
                    model_path="",
                    success=True,
                )
                if conversation_id:
                    _update_memory_after_run(
                        conversation_id,
                        user_input,
                        "计划已生成，等待澄清问题回答",
                        True,
                    )
                return True, "计划已生成，等待澄清问题回答", True

            except ReActNeedsReorchestrate as e:
                # 无效迭代/建议重新编排：调用 PlannerOrchestrator.reorchestrate 并返回用户说明
                from agent.react.iteration_controller import REORCHESTRATE_PREFIX
                from agent.planner.orchestrator import PlannerOrchestrator

                failure_summary = (e.message or "").replace(REORCHESTRATE_PREFIX, "").strip()
                orchestrator = PlannerOrchestrator(
                    backend=backend,
                    api_key=api_key,
                    base_url=base_url,
                    ollama_url=ollama_url,
                    model=model,
                )
                try:
                    _task_plan, _ctx, _serial_plan, user_message = orchestrator.reorchestrate(
                        user_input, failure_summary, context=memory_context
                    )
                except Exception as orch_e:
                    logger.warning("重新编排失败: %s", orch_e)
                    user_message = "执行遇到问题，建议重新编排任务；重新编排调用失败: " + str(orch_e)
                context_manager.add_conversation(
                    user_input=user_input,
                    plan={"architecture": "react", "status": "reorchestrate"},
                    model_path="",
                    success=True,
                )
                if conversation_id:
                    _update_memory_after_run(
                        conversation_id,
                        user_input,
                        user_message,
                        True,
                    )
                return True, user_message, True

            context_manager.add_conversation(
                user_input=user_input,
                plan={"architecture": "react"},
                model_path=str(model_path),
                success=True,
            )
            if conversation_id:
                _update_memory_after_run(
                    conversation_id,
                    user_input,
                    f"模型已生成: {model_path}",
                    True,
                )
            return True, f"模型已生成: {model_path}", False
        else:
            context = memory_context
            planner = get_agent(
                "planner",
                backend=backend,
                api_key=api_key,
                base_url=base_url,
                ollama_url=ollama_url,
                model=model,
            )
            plan = planner.parse(user_input, context=context)
            runner = COMSOLRunner()
            model_path = runner.create_model_from_plan(plan, output)
            context_manager.add_conversation(
                user_input=user_input,
                plan=plan.to_dict(),
                model_path=str(model_path),
                success=True,
            )
            if conversation_id:
                _update_memory_after_run(
                    conversation_id,
                    user_input,
                    f"模型已生成: {model_path}",
                    True,
                )
            return True, f"模型已生成: {model_path}", False
    except Exception as e:
        logger.exception("do_run 失败")
        context_manager.add_conversation(user_input=user_input, success=False, error=str(e))
        if conversation_id:
            _update_memory_after_run(conversation_id, user_input, str(e), False)
        return False, str(e), False


def do_plan_mode(
    user_input: str,
    conversation_id: Optional[str] = None,
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    ollama_url: Optional[str] = None,
    model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[bool, str, Optional[Dict[str, Any]], bool]:
    """
    Plan 模式：多轮交互式形成 plan.json，满意后返回 should_enter_core=True 与 plan_dict。
    返回 (ok, reply_text, plan_dict, should_enter_core)。
    """
    _ensure_logging(verbose)
    try:
        context_manager = get_context_manager(conversation_id)
        from agent.run.plan_mode import PlanModeHandler

        handler = PlanModeHandler(
            context_manager=context_manager,
            get_agent=get_agent,
            backend=backend,
            api_key=api_key,
            base_url=base_url,
            ollama_url=ollama_url,
            model=model,
        )
        reply, plan_dict, should_enter_core = handler.process(user_input)
        return True, reply, plan_dict, should_enter_core
    except Exception as e:
        logger.exception("do_plan_mode 失败: %s", e)
        return False, str(e), None, False


def do_plan(
    user_input: str,
    output_path: Optional[Path] = None,
    verbose: bool = False,
) -> Tuple[bool, str]:
    """计划模式：自然语言 -> JSON。返回 (成功, 要显示的文本)。"""
    _ensure_logging(verbose)
    try:
        planner = get_agent("planner")
        plan = planner.parse(user_input)
        plan_dict = plan.to_dict()
        text = json.dumps(plan_dict, ensure_ascii=False, indent=2)
        if output_path:
            output_path.write_text(text, encoding="utf-8")
            return True, f"计划已保存到: {output_path}\n\n{text}"
        return True, text
    except Exception as e:
        logger.exception("do_plan 失败")
        return False, str(e)


def do_exec_from_file(
    plan_file: Path,
    output: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[bool, str]:
    """根据 JSON 计划文件执行：创建模型。"""
    _ensure_logging(verbose)
    try:
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
        plan = GeometryPlan.from_dict(plan_data)
        runner = COMSOLRunner()
        model_path = runner.create_model_from_plan(plan, output)
        return True, f"模型已生成: {model_path}"
    except Exception as e:
        logger.exception("do_exec 失败")
        return False, str(e)


def do_demo(verbose: bool = False) -> Tuple[bool, str]:
    """运行演示用例（与桌面端快捷提示词一致，覆盖仅几何、材料、物理场、研究、完整流程），返回汇总文本。"""
    _ensure_logging(verbose)
    lines = ["Multiphysics Modeling Agent 演示（测试各链路）\n"]
    planner = get_agent("planner")
    for i, case in enumerate(QUICK_TEST_PROMPTS, 1):
        lines.append(f"示例 {i}: {case}")
        try:
            plan = planner.parse(case)
            shapes = getattr(plan, "shapes", None)
            if shapes is not None:
                lines.append(f"  解析成功: {len(shapes)} 个形状, 模型名: {getattr(plan, 'model_name', 'model')}, 单位: {getattr(plan, 'units', 'm')}")
            else:
                # 编排器返回 TaskPlan，可能含 geometry/material/physics/study
                geom = getattr(plan, "geometry", None)
                n_shapes = len(getattr(geom, "shapes", [])) if geom else 0
                lines.append(f"  解析成功: 几何 {n_shapes} 个形状, 含 material={getattr(plan, 'material', None) is not None}, physics={getattr(plan, 'physics', None) is not None}, study={getattr(plan, 'study', None) is not None}")
        except Exception as e:
            lines.append(f"  解析失败: {e}")
        lines.append("")
    return True, "\n".join(lines)


def do_doctor(verbose: bool = False) -> Tuple[bool, str]:
    """运行环境诊断，返回结果文本。"""
    _ensure_logging(verbose)
    settings = get_settings()
    status = settings.show_config_status()
    result = check_environment()
    lines = [f"各后端配置状态: {status}", ""]
    if result.is_valid():
        lines.append("环境检查通过")
    else:
        lines.append("环境检查失败")
    for e in result.errors:
        lines.append(f"  错误: {e}")
    for w in result.warnings:
        lines.append(f"  警告: {w}")
    for i in result.info:
        lines.append(f"  {i}")
    return result.is_valid(), "\n".join(lines)


def do_context_show(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """上下文摘要。conversation_id 存在时查看该会话的摘要。"""
    cm = get_context_manager(conversation_id)
    summary = cm.load_summary()
    if summary:
        return True, f"{summary.summary}\n\n最后更新: {summary.last_updated[:19]}"
    return True, "暂无上下文摘要"


def do_context_get_summary(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """仅返回当前会话的摘要原文（供设置页编辑）。"""
    cm = get_context_manager(conversation_id)
    summary = cm.load_summary()
    if summary:
        return True, summary.summary
    return True, ""


def do_context_set_summary(conversation_id: Optional[str], text: str) -> Tuple[bool, str]:
    """设置当前会话的摘要原文（用户编辑记忆）。"""
    if not conversation_id:
        return False, "缺少 conversation_id"
    cm = get_context_manager(conversation_id)
    cm.set_summary_text(text)
    return True, "记忆已保存"


def do_ollama_ping(ollama_url: str) -> Tuple[bool, str]:
    """测试 Ollama 服务连通性。"""
    url = (ollama_url or "").strip()
    if not url:
        return False, "请填写 Ollama 地址"
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    try:
        import requests
        r = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        if r.status_code == 200:
            models = r.json().get("models", [])
            names = [m.get("name", "") for m in models[:5]]
            return True, f"连接成功，可用模型: {', '.join(names) or '无'}"
        return False, f"响应异常: HTTP {r.status_code}"
    except Exception as e:
        return False, f"连接失败: {e}"


def do_context_history(limit: int = 10, conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """对话历史。"""
    cm = get_context_manager(conversation_id)
    history_list = cm.get_recent_history(limit)
    lines = [f"最近 {len(history_list)} 条对话历史\n"]
    for i, entry in enumerate(history_list, 1):
        ts = entry.get("timestamp", "")[:19]
        ui = (entry.get("user_input") or "")[:60]
        ok = entry.get("success", True)
        st = "成功" if ok else "失败"
        lines.append(f"{i}. [{st}] {ts} {ui}...")
    return True, "\n".join(lines)


def do_context_stats(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """上下文统计。"""
    cm = get_context_manager(conversation_id)
    data = cm.get_stats()
    lines = [
        f"总对话数: {data['total_conversations']}",
        f"成功: {data['successful']}",
        f"失败: {data['failed']}",
    ]
    if data.get("recent_shapes"):
        lines.append(f"最近形状: {', '.join(data['recent_shapes'])}")
    if data.get("preferences"):
        lines.append(f"用户偏好: {data['preferences']}")
    return True, "\n".join(lines)


def do_context_clear(conversation_id: Optional[str] = None) -> Tuple[bool, str]:
    """清除对话历史。"""
    get_context_manager(conversation_id).clear_history()
    return True, "对话历史已清除"


def do_config_save(env_updates: Optional[dict] = None) -> Tuple[bool, str]:
    """将配置写入项目根目录的 .env 文件并重载配置，供桌面端保存后同步。"""
    if not env_updates:
        return False, "无配置项"
    from agent.utils.config import get_project_root, reload_settings

    root = get_project_root()
    env_path = root / ".env"
    env_keys = [
        "LLM_BACKEND",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "KIMI_API_KEY",
        "KIMI_MODEL",
        "OPENAI_COMPATIBLE_API_KEY",
        "OPENAI_COMPATIBLE_BASE_URL",
        "OPENAI_COMPATIBLE_MODEL",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "COMSOL_JAR_PATH",
        "JAVA_HOME",
    ]
    # 读取已有行
    if env_path.exists():
        lines_out = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines_out = []
    # 键 -> 行索引（只记第一个出现的键）
    key_to_idx: dict[str, int] = {}
    for i, line in enumerate(lines_out):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            key = s.split("=", 1)[0].strip()
            if key not in key_to_idx:
                key_to_idx[key] = i
    # 更新或追加
    for k in env_keys:
        v = env_updates.get(k)
        if v is None:
            continue
        v_str = str(v).strip()
        new_line = f"{k}={v_str}"
        if k in key_to_idx:
            lines_out[key_to_idx[k]] = new_line
        else:
            lines_out.append(new_line)
            key_to_idx[k] = len(lines_out) - 1
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
        reload_settings()
        return True, "配置已保存并已加载，将应用于后续 mph-agent 调用"
    except Exception as e:
        return False, f"写入 .env 失败: {e}"


def do_list_apis(
    query: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> Tuple[bool, str]:
    """
    列出已集成的 COMSOL 官方 Java API 包装函数。
    返回 JSON 文本，包含 items/total/limit/offset 等字段。
    """
    try:
        ctrl = JavaAPIController()
        result = ctrl.list_official_api_wrappers(query=query, limit=limit, offset=offset)
        if result.get("status") != "success":
            return False, result.get("message", "list_official_api_wrappers 调用失败")
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return True, text
    except Exception as e:
        logger.exception("do_list_apis 失败")
        return False, str(e)
