"""CLI 入口：无参数启动桌面应用；tui-bridge 供 Tauri 后端子进程调用。"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    """项目根目录：源码运行时为含 pyproject.toml 的目录，pip 安装后为当前工作目录。"""
    p = Path(__file__).resolve().parent
    if (p / "pyproject.toml").exists():
        return p
    return Path.cwd()


def _launch_desktop(root: Path) -> None:
    """启动 Tauri 桌面应用。开发时用 npm run tauri dev，发布后直接运行可执行文件。"""
    desktop_dir = root / "desktop"

    # 优先查找打包后的可执行文件
    if sys.platform == "win32":
        bundled = desktop_dir / "src-tauri" / "target" / "release" / "mph-agent-desktop.exe"
    else:
        bundled = desktop_dir / "src-tauri" / "target" / "release" / "mph-agent-desktop"

    if bundled.exists():
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    [str(bundled)],
                    cwd=root,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    [str(bundled)],
                    cwd=root,
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception as e:
            print(f"桌面应用启动失败: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # 开发模式：npm run tauri dev
    if not (desktop_dir / "package.json").exists():
        print(
            "错误: 未找到桌面应用项目（desktop/package.json），请从仓库根目录运行。",
            file=sys.stderr,
        )
        sys.exit(1)

    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    if not shutil.which(npm_cmd):
        print("错误: 未检测到 npm，开发模式需要 Node.js。请安装后重试。", file=sys.stderr)
        sys.exit(1)

    if not shutil.which("cargo"):
        print(
            "错误: 未检测到 cargo，Tauri 开发模式需要 Rust。请安装后重试: https://rustup.rs",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        subprocess.run(
            [npm_cmd, "run", "tauri", "dev"],
            cwd=desktop_dir,
            env=env,
            check=False,
        )
    except Exception as e:
        print(f"桌面应用启动失败: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """入口：无参数启动桌面应用；tui-bridge 供 Tauri 后端调用；其它打印用法并退出。"""
    root = _project_root()
    args = sys.argv[1:]

    if not args or (len(args) == 1 and args[0] in ("--help", "-h", "--interactive", "-i")):
        if args and args[0] in ("--help", "-h"):
            print("Usage: uv run python cli.py  或  uv run python cli.py tui-bridge")
            print("  无参数启动桌面应用；tui-bridge 供内部调用，勿直接使用。")
        _launch_desktop(root)
        return

    if args[0] == "tui-bridge":
        sys.stdout.write('{"_ready":true}\n')
        sys.stdout.flush()

        from dotenv import load_dotenv
        from agent.utils.java_runtime import ensure_java_home_from_venv

        load_dotenv(root / ".env")
        ensure_java_home_from_venv(root)

        from agent.run.tui_bridge import main as bridge_main

        bridge_main()
        return

    print("Usage: uv run python cli.py  或  uv run python cli.py tui-bridge", file=sys.stderr)
    print("  无参数启动桌面应用；run/plan/exec 等请在桌面应用内使用。", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
