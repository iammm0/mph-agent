# PyInstaller spec for mph-agent-bridge (desktop 安装包内嵌的 Python 后端)
# 在项目根目录执行: pyinstaller desktop/scripts/bridge.spec

import sys
from pathlib import Path

# 项目根（spec 在 desktop/scripts/bridge.spec，SPECPATH = desktop/scripts）
ROOT = Path(SPECPATH).resolve().parent.parent


def _datas_if_exists(*parts: str):
    """仅打包仍存在的数据目录，避免裁剪后的路径把 CI 打挂。"""
    src = ROOT.joinpath(*parts)
    if not src.exists():
        return []
    return [(str(src), "/".join(parts))]


a = Analysis(
    [str(ROOT / "bridge_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        *_datas_if_exists("agent", "prompts"),
        *_datas_if_exists("agent", "skills", "library"),
        # clawcode 已精简，不再打包已删除的 reference_data
    ],
    hiddenimports=[
        "agent",
        "agent.run",
        "agent.run.tui_bridge",
        "agent.run.actions",
        "agent.core",
        "agent.executor",
        "agent.executor.comsol_ops_cli",
        "agent.executor.mph_backend",
        "agent.executor.compute_backend",
        "agent.clawcode_bridge",
        "agent.clawcode.compact",
        "agent.clawcode.microcompact",
        "agent.clawcode.token_budget",
        "agent.clawcode.tokenizer_runtime",
        "agent.clawcode.plan_runtime",
        "agent.clawcode.task_runtime",
        "agent.clawcode.agent_session",
        "agent.clawcode.agent_types",
        "agent.agents.analysis_agent",
        "agent.planner",
        "agent.react",
        "agent.utils",
        "agent.utils.config",
        "agent.utils.java_runtime",
        "scripts.sync_comsol_case_library",
        "agent.schemas",
        "dotenv",
        "pydantic",
        "pydantic_settings",
        "openai",
        "litellm",
        "requests",
        "jpype",
        "_jpype",
        "loguru",
        "questionary",
        "fastapi",
        "uvicorn",
        "starlette",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "tensorflow", "transformers", "sentence_transformers",
        "IPython", "jupyter", "matplotlib", "PIL", "cv2",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mph-agent-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 不弹控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
