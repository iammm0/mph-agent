"""运行入口：do_run/do_plan/do_exec 与 TUI 桥接。"""
from agent.run.actions import (
    do_run,
    do_plan,
    do_plan_mode,
    do_exec_from_file,
    do_demo,
    do_doctor,
    do_context_show,
    do_context_get_summary,
    do_context_set_summary,
    do_context_history,
    do_context_stats,
    do_context_clear,
    do_ollama_ping,
    do_config_save,
)
from agent.run.tui_bridge import main as tui_bridge_main

__all__ = [
    "do_run",
    "do_plan",
    "do_plan_mode",
    "do_exec_from_file",
    "do_demo",
    "do_doctor",
    "do_context_show",
    "do_context_get_summary",
    "do_context_set_summary",
    "do_context_history",
    "do_context_stats",
    "do_context_clear",
    "do_ollama_ping",
    "do_config_save",
    "tui_bridge_main",
]
