"""TUI 桥接：从 stdin 读 JSON 行，调用 agent.run.actions，向 stdout 写 JSON 行。供 Bun OpenTUI 前端通过子进程调用。"""
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional, TextIO

# 进程一启动就写一条日志（不依赖 MPH_AGENT_BRIDGE_DEBUG），便于确认进程是否曾启动；若 import 失败也能在下面捕获并写入同一文件
def _early_log_path() -> str:
    return os.path.join(os.environ.get("TEMP", os.environ.get("TMP", "/tmp")), "mph-agent-bridge-debug.log")

def _early_log(msg: str) -> None:
    try:
        with open(_early_log_path(), "a", encoding="utf-8") as f:
            f.write(msg)
            f.flush()
    except OSError:
        pass

_early_log("Bridge process started\n")
_early_log(f"cwd={os.getcwd()!r} executable={sys.executable!r}\n")

try:
    from agent.run.actions import (
        do_run,
        do_chat,
        do_plan,
        do_plan_mode,
        do_discuss,
        do_case,
        do_case_library_list,
        do_case_library_sync,
        do_case_library_sync_status,
        do_doc_kb_import,
        do_doc_kb_search,
        do_doc_kb_status,
        do_skills_list_local,
        do_skills_create_local,
        do_skills_import_local,
        do_skills_list_online,
        do_ops_catalog,
        do_exec_from_file,
        do_demo,
        do_doctor,
        do_context_show,
        do_context_get_summary,
        do_context_prompt_context,
        do_context_set_summary,
        do_context_history,
        do_context_stats,
        do_context_clear,
        do_ollama_ping,
        do_config_save,
        do_conversation_title_suggest,
    )
    from agent.core.events import EventBus, Event, EventType
    from agent.executor.java_api_controller import JavaAPIController
    from agent.utils.context_manager import get_all_models_from_context, get_context_manager
except Exception as e:
    _early_log("Import failed:\n" + "".join(traceback.format_exception(type(e), e, e.__traceback__)))
    raise


def _bridge_debug() -> bool:
    """是否启用 Bridge 调试（环境变量 MPH_AGENT_BRIDGE_DEBUG=1 时在 stderr 与日志文件打印请求/响应与异常）。"""
    return os.environ.get("MPH_AGENT_BRIDGE_DEBUG", "").strip() in ("1", "true", "True")


def _bridge_debug_log_path() -> Path:
    """调试日志文件路径（与平台无关，放在 temp 目录）。"""
    return Path(os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))).resolve() / "mph-agent-bridge-debug.log"


_debug_log_file: Optional[TextIO] = None


def _debug_log(msg: str) -> None:
    """调试模式下写入 stderr 并追加到日志文件，每次写入后立即 flush。"""
    if not _bridge_debug():
        return
    sys.stderr.write(msg)
    sys.stderr.flush()
    global _debug_log_file
    if _debug_log_file is None:
        try:
            _debug_log_file = open(_bridge_debug_log_path(), "a", encoding="utf-8")
        except OSError:
            return
    try:
        _debug_log_file.write(msg)
        _debug_log_file.flush()
    except OSError:
        pass


def _reply(ok: bool, message: str, **extra: Any) -> None:
    payload: dict = {"ok": ok, "message": message, **extra}
    line = json.dumps(_json_safe(payload), ensure_ascii=False) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def _json_safe(obj: Any) -> Any:
    """将对象转为 JSON 可序列化形式。"""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return _json_safe(obj.model_dump(mode="json"))
        except TypeError:
            return _json_safe(obj.model_dump())
    if hasattr(obj, "dict"):
        try:
            return _json_safe(obj.dict())
        except Exception:
            pass
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _emit_event(event: Event) -> None:
    """将事件序列化为 JSON 行写入 stdout。"""
    payload = {
        "_event": True,
        "type": event.type.value,
        "data": _json_safe(event.data),
        "iteration": event.iteration,
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def _handle(req: dict[str, Any]) -> None:
    cmd = (req.get("cmd") or "").strip()
    if not cmd:
        _reply(False, "缺少 cmd")
        return

    from agent.utils.context_manager import (
        ensure_workspace_layout,
        set_active_workspace_dir,
    )

    workspace_dir = req.get("workspace_dir") or None
    set_active_workspace_dir(workspace_dir)
    if workspace_dir:
        try:
            ensure_workspace_layout(workspace_dir)
        except Exception:
            pass

    try:
        if cmd == "chat":
            event_bus = EventBus()
            event_bus.subscribe_all(_emit_event)
            replied = False
            try:
                try:
                    ok, msg, plan_dict, plan_confirmed, clarifying_questions, executed_run = (
                        do_chat(
                            user_input=(req.get("input") or "").strip(),
                            conversation_id=req.get("conversation_id") or None,
                            backend=req.get("backend") or None,
                            api_key=req.get("api_key") or None,
                            base_url=req.get("base_url") or None,
                            ollama_url=req.get("ollama_url") or None,
                            model=req.get("model") or None,
                            output=req.get("output") or None,
                            workspace_dir=req.get("workspace_dir") or None,
                            skip_check=req.get("skip_check", False),
                            verbose=req.get("verbose", False),
                            clarifying_answers=req.get("clarifying_answers") or None,
                            event_bus=event_bus,
                        )
                    )
                    _reply(
                        ok,
                        msg,
                        plan=plan_dict,
                        plan_confirmed=plan_confirmed,
                        clarifying_questions=clarifying_questions or [],
                        plan_needs_clarification=bool(clarifying_questions),
                        executed_run=executed_run,
                    )
                    replied = True
                except Exception as e:
                    if _bridge_debug():
                        _debug_log("".join(traceback.format_exception(type(e), e, e.__traceback__)))
                    _emit_event(Event(type=EventType.ERROR, data={"message": str(e)}))
                    _reply(False, str(e))
                    replied = True
            finally:
                if not replied:
                    try:
                        _reply(False, "chat 未返回响应即退出，请设置 COMSOL_AGENT_BRIDGE_DEBUG=1 查看日志")
                    except Exception:
                        pass
            return

        if cmd == "run":
            event_bus = EventBus()
            event_bus.subscribe_all(_emit_event)
            replied = False
            try:
                try:
                    ok, msg, plan_needs_clarification = do_run(
                        user_input=(req.get("input") or "").strip(),
                        output=req.get("output") or None,
                        workspace_dir=req.get("workspace_dir") or None,
                        use_react=req.get("use_react", True),
                        no_context=req.get("no_context", False),
                        conversation_id=req.get("conversation_id") or None,
                        backend=req.get("backend") or None,
                        api_key=req.get("api_key") or None,
                        base_url=req.get("base_url") or None,
                        ollama_url=req.get("ollama_url") or None,
                        model=req.get("model") or None,
                        skip_check=req.get("skip_check", False),
                        verbose=req.get("verbose", False),
                        event_bus=event_bus,
                        clarifying_answers=req.get("clarifying_answers") or None,
                    )
                    _reply(ok, msg, plan_needs_clarification=plan_needs_clarification)
                    replied = True
                except Exception as e:
                    if _bridge_debug():
                        _debug_log("".join(traceback.format_exception(type(e), e, e.__traceback__)))
                    _emit_event(Event(type=EventType.ERROR, data={"message": str(e)}))
                    _reply(False, str(e))
                    replied = True
            finally:
                if not replied:
                    try:
                        _reply(False, "run 未返回响应即退出，请设置 COMSOL_AGENT_BRIDGE_DEBUG=1 查看日志")
                    except Exception:
                        pass
            return

        if cmd == "plan":
            event_bus = None
            if req.get("stream"):
                event_bus = EventBus()
                event_bus.subscribe_all(_emit_event)
            ok, msg, plan_dict, plan_confirmed, clarifying_questions = do_plan_mode(
                user_input=(req.get("input") or "").strip(),
                conversation_id=req.get("conversation_id") or None,
                backend=req.get("backend") or None,
                api_key=req.get("api_key") or None,
                base_url=req.get("base_url") or None,
                ollama_url=req.get("ollama_url") or None,
                model=req.get("model") or None,
                clarifying_answers=req.get("clarifying_answers") or None,
                verbose=req.get("verbose", False),
                event_bus=event_bus,
            )
            _reply(
                ok,
                msg,
                plan=plan_dict,
                plan_confirmed=plan_confirmed,
                clarifying_questions=clarifying_questions or [],
                plan_needs_clarification=bool(clarifying_questions),
            )
            return

        if cmd == "discuss":
            event_bus = None
            if req.get("stream"):
                event_bus = EventBus()
                event_bus.subscribe_all(_emit_event)
            ok, msg, card = do_discuss(
                user_input=(req.get("input") or "").strip(),
                conversation_id=req.get("conversation_id") or None,
                verbose=req.get("verbose", False),
                backend=req.get("backend") or None,
                api_key=req.get("api_key") or None,
                base_url=req.get("base_url") or None,
                ollama_url=req.get("ollama_url") or None,
                model=req.get("model") or None,
                event_bus=event_bus,
            )
            _reply(ok, msg, discussion_card=card)
            return

        if cmd == "case":
            model_path = (req.get("model_path") or req.get("path") or "").strip()
            ok, msg, case_json, saved_path = do_case(
                model_path=model_path,
                conversation_id=req.get("conversation_id") or None,
                verbose=req.get("verbose", False),
            )
            _reply(ok, msg, case_generated=case_json, saved_path=saved_path)
            return

        if cmd == "case_library_list":
            try:
                limit = int(req.get("limit") or 200)
            except Exception:
                limit = 200
            try:
                offset = int(req.get("offset") or 0)
            except Exception:
                offset = 0
            ok, msg, result = do_case_library_list(
                query=(req.get("query") or "").strip() or None,
                category=(req.get("category") or "").strip() or None,
                limit=limit,
                offset=offset,
                verbose=req.get("verbose", False),
            )
            _reply(
                ok,
                msg,
                items=result.get("items", []),
                total=result.get("total", 0),
                limit=result.get("limit", limit),
                offset=result.get("offset", offset),
                generated_at=result.get("generated_at"),
                metadata=result.get("metadata", {}),
            )
            return

        if cmd == "case_library_sync":
            def _int(name: str, default: int) -> int:
                try:
                    return int(req.get(name) or default)
                except Exception:
                    return default

            def _float(name: str, default: float) -> float:
                try:
                    return float(req.get(name) or default)
                except Exception:
                    return default

            ok, msg, state = do_case_library_sync(
                start_page=_int("start_page", 1),
                end_page=_int("end_page", 0),
                limit=_int("limit", 0),
                workers=_int("workers", 4),
                timeout=_float("timeout", 20.0),
                delay_ms=_int("delay_ms", 100),
                verbose=req.get("verbose", False),
            )
            _reply(ok, msg, sync=state)
            return

        if cmd == "case_library_sync_status":
            ok, msg, state = do_case_library_sync_status(verbose=req.get("verbose", False))
            _reply(ok, msg, sync=state)
            return

        if cmd == "doc_kb_import":
            def _int(name: str, default: int) -> int:
                try:
                    return int(req.get(name) or default)
                except Exception:
                    return default

            ok, msg, state = do_doc_kb_import(
                source_path=(req.get("source_path") or "").strip(),
                version=(req.get("version") or "6.3").strip() or "6.3",
                limit=_int("limit", 0),
                chunk_chars=_int("chunk_chars", 2400),
                overlap_chars=_int("overlap_chars", 240),
                verbose=req.get("verbose", False),
            )
            _reply(ok, msg, sync=state)
            return

        if cmd == "doc_kb_status":
            ok, msg, state = do_doc_kb_status(verbose=req.get("verbose", False))
            _reply(ok, msg, sync=state)
            return

        if cmd == "doc_kb_search":
            try:
                limit = int(req.get("limit") or 5)
            except Exception:
                limit = 5
            ok, msg, result = do_doc_kb_search(
                query=(req.get("query") or "").strip(),
                limit=limit,
                verbose=req.get("verbose", False),
            )
            _reply(
                ok,
                msg,
                items=result.get("items", []),
                total=result.get("total", 0),
                query=result.get("query", ""),
                limit=result.get("limit", limit),
            )
            return

        if cmd == "skills_list_local":
            ok, msg, result = do_skills_list_local(verbose=req.get("verbose", False))
            _reply(
                ok,
                msg,
                items=result.get("items", []),
                total=result.get("total", 0),
            )
            return

        if cmd == "skills_create_local":
            tags = req.get("tags")
            triggers = req.get("triggers")
            ok, msg, result = do_skills_create_local(
                name=(req.get("name") or "").strip(),
                description=(req.get("description") or "").strip(),
                tags=tags if isinstance(tags, list) else None,
                triggers=triggers if isinstance(triggers, list) else None,
                verbose=req.get("verbose", False),
            )
            _reply(ok, msg, item=result.get("item"))
            return

        if cmd == "skills_import_local":
            ok, msg, result = do_skills_import_local(
                source_path=(req.get("source_path") or "").strip(),
                verbose=req.get("verbose", False),
            )
            _reply(ok, msg, item=result.get("item"))
            return

        if cmd == "skills_list_online":
            ok, msg, result = do_skills_list_online(verbose=req.get("verbose", False))
            _reply(
                ok,
                msg,
                items=result.get("items", []),
                total=result.get("total", 0),
            )
            return

        if cmd == "ops_catalog":
            query = (req.get("query") or "").strip() or None
            try:
                raw_limit = req.get("limit")
                # 显式传 0 表示「不分页、返回全部」（避免 ``0 or 200`` 误当成 200）
                if raw_limit is None:
                    limit = 200
                else:
                    limit = int(raw_limit)
            except Exception:
                limit = 200
            try:
                offset = int(req.get("offset") or 0)
            except Exception:
                offset = 0
            ok, msg, result = do_ops_catalog(
                query=query,
                limit=limit,
                offset=offset,
                wrappers_only=bool(req.get("wrappers_only")),
                verbose=req.get("verbose", False),
            )
            _reply(
                ok,
                msg,
                items=result.get("items", []),
                total=result.get("total", 0),
                limit=result.get("limit", limit),
                offset=result.get("offset", offset),
                categories=result.get("categories", []),
            )
            return

        if cmd == "exec":
            path_str = (req.get("path") or "").strip()
            if not path_str:
                _reply(False, "缺少 path")
                return
            path = Path(path_str)
            if not path.exists():
                _reply(False, f"文件不存在: {path}")
                return
            ok, msg = do_exec_from_file(
                plan_file=path,
                output=req.get("output") or None,
                verbose=req.get("verbose", False),
            )
            _reply(ok, msg)
            return

        if cmd == "demo":
            ok, msg = do_demo(verbose=req.get("verbose", False))
            _reply(ok, msg)
            return

        if cmd == "doctor":
            ok, msg = do_doctor(verbose=req.get("verbose", False))
            _reply(ok, msg)
            return

        if cmd == "context_show":
            ok, msg = do_context_show(conversation_id=req.get("conversation_id") or None)
            _reply(ok, msg)
            return

        if cmd == "context_get_summary":
            ok, msg = do_context_get_summary(conversation_id=req.get("conversation_id") or None)
            _reply(ok, msg)
            return

        if cmd == "context_prompt_context":
            ok, msg = do_context_prompt_context(conversation_id=req.get("conversation_id") or None)
            _reply(ok, msg)
            return

        if cmd == "context_set_summary":
            text = (req.get("text") or "").strip()
            ok, msg = do_context_set_summary(
                conversation_id=req.get("conversation_id") or None,
                text=text,
            )
            _reply(ok, msg)
            return

        if cmd == "ollama_ping":
            ok, msg = do_ollama_ping(ollama_url=req.get("ollama_url") or "")
            _reply(ok, msg)
            return

        if cmd == "context_history":
            limit = req.get("limit", 10)
            ok, msg = do_context_history(limit=limit, conversation_id=req.get("conversation_id") or None)
            _reply(ok, msg)
            return

        if cmd == "context_stats":
            ok, msg = do_context_stats(conversation_id=req.get("conversation_id") or None)
            _reply(ok, msg)
            return

        if cmd == "context_clear":
            ok, msg = do_context_clear(conversation_id=req.get("conversation_id") or None)
            _reply(ok, msg)
            return

        if cmd == "config_save":
            config = req.get("config")
            if isinstance(config, dict):
                ok, msg = do_config_save(config)
            else:
                ok, msg = False, "缺少 config"
            _reply(ok, msg)
            return

        if cmd == "model_preview":
            path_str = (req.get("path") or req.get("model_path") or "").strip()
            if not path_str:
                _reply(False, "缺少 path 或 model_path")
                return
            if not Path(path_str).exists():
                _reply(False, "模型文件不存在", image_base64=None)
                return
            try:
                ctrl = JavaAPIController()
                width = int(req.get("width") or 640)
                height = int(req.get("height") or 480)
                result = ctrl.export_model_preview(path_str, width=width, height=height)
                ok = result.get("status") == "success"
                _reply(ok, result.get("message", ""), image_base64=result.get("image_base64"))
            except Exception as e:
                _reply(False, str(e), image_base64=None)
            return

        if cmd == "models_list":
            limit = int(req.get("limit") or 50)
            try:
                models = get_all_models_from_context(limit=limit)
                _reply(True, "ok", models=models)
            except Exception as e:
                _reply(False, str(e), models=[])
            return

        if cmd == "list_apis":
            query = (req.get("query") or "").strip() or None
            try:
                limit = int(req.get("limit") or 200)
            except Exception:
                limit = 200
            try:
                offset = int(req.get("offset") or 0)
            except Exception:
                offset = 0
            try:
                ctrl = JavaAPIController()
                result = ctrl.list_official_api_wrappers(
                    query=query, limit=limit, offset=offset
                )
                ok = result.get("status") == "success"
                msg = result.get("message", "ok" if ok else "error")
                _reply(
                    ok,
                    msg,
                    apis=result.get("items", []),
                    total=result.get("total", 0),
                    limit=result.get("limit", limit),
                    offset=result.get("offset", offset),
                )
            except Exception as e:
                _reply(False, str(e), apis=[], total=0, limit=limit, offset=offset)
            return

        if cmd == "conversation_delete":
            conversation_id = (req.get("conversation_id") or "").strip()
            if not conversation_id:
                _reply(False, "缺少 conversation_id", deleted_paths=[])
                return
            try:
                cm = get_context_manager(conversation_id=conversation_id)
                deleted_paths = cm.delete_conversation_and_models()
                _reply(True, "已删除对话及其关联的 COMSOL 模型", deleted_paths=deleted_paths)
            except Exception as e:
                _reply(False, str(e), deleted_paths=[])
            return

        if cmd == "conversation_title_suggest":
            ok, title = do_conversation_title_suggest(
                user_input=(req.get("input") or "").strip(),
                backend=req.get("backend") or None,
                api_key=req.get("api_key") or None,
                base_url=req.get("base_url") or None,
                ollama_url=req.get("ollama_url") or None,
                model=req.get("model") or None,
            )
            _reply(ok, title, title=title if ok else None)
            return

        _reply(False, f"未知命令: {cmd}")
    except Exception as e:
        if _bridge_debug():
            _debug_log("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        _reply(False, str(e))


def main() -> None:
    """从 stdin 按行读 JSON，处理并写一行 JSON 到 stdout。"""
    if sys.stdin.isatty():
        sys.stderr.write("tui-bridge: 请通过管道或子进程调用，不要直接交互运行\n")
        sys.exit(1)
    if _bridge_debug():
        log_path = _bridge_debug_log_path()
        _debug_log(f"[bridge] 调试模式已开启，日志文件: {log_path}\n")

        def _excepthook(typ, val, tb):  # noqa: N807
            msg = "".join(traceback.format_exception(typ, val, tb))
            _debug_log(f"[bridge] 未捕获异常:\n{msg}")
            sys.__excepthook__(typ, val, tb)

        sys.excepthook = _excepthook

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if _bridge_debug():
            _debug_log(f"[bridge] 收到请求: {line[:200]}{'...' if len(line) > 200 else ''}\n")
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            if _bridge_debug():
                _debug_log("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            _reply(False, f"JSON 解析错误: {e}")
            continue
        try:
            _handle(req)
        except BaseException as e:
            if _bridge_debug():
                _debug_log("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            _reply(False, str(e))
            raise


if __name__ == "__main__":
    main()
