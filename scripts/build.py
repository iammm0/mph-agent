"""打包脚本 - 带进度条和超时处理"""
import subprocess
import sys
import os
import threading
import time
from pathlib import Path
from typing import Optional

# 设置 UTF-8 编码
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)  # UTF-8
    except Exception:
        pass

# 确保标准输出使用 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("警告: rich 未安装，将使用简单输出模式")

console = Console() if RICH_AVAILABLE else None


class BuildTimeoutError(Exception):
    """构建超时异常"""
    pass


def run_with_timeout(
    cmd: list,
    timeout: int = 300,
    env: Optional[dict] = None,
    cwd: Optional[str] = None
) -> tuple[int, str]:
    """
    运行命令并带超时处理
    
    Args:
        cmd: 命令列表
        timeout: 超时时间（秒）
        env: 环境变量
        cwd: 工作目录
    
    Returns:
        (退出代码, 输出文本)
    
    Raises:
        BuildTimeoutError: 超时
    """
    process = None
    output_lines = []
    error_occurred = [False]
    
    def read_output(pipe, is_stderr=False):
        """读取输出"""
        try:
            for line in iter(pipe.readline, ''):
                if not line:
                    break
                line = line.rstrip()
                if line:
                    output_lines.append((is_stderr, line))
        except Exception:
            pass
        finally:
            pipe.close()
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1
        )
        
        # 启动输出读取线程
        stdout_thread = threading.Thread(target=read_output, args=(process.stdout, False))
        stderr_thread = threading.Thread(target=read_output, args=(process.stderr, True))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        # 等待进程完成或超时
        start_time = time.time()
        while process.poll() is None:
            if time.time() - start_time > timeout:
                process.terminate()
                time.sleep(1)
                if process.poll() is None:
                    process.kill()
                raise BuildTimeoutError(f"构建超时（超过 {timeout} 秒）")
            time.sleep(0.1)
        
        # 等待输出线程完成
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        
        return process.returncode, '\n'.join(line for _, line in output_lines)
        
    except BuildTimeoutError:
        raise
    except Exception as e:
        if process:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        raise RuntimeError(f"执行命令失败: {e}") from e


def build():
    """构建分发包"""
    if console:
        console.print(Panel.fit("[bold cyan]构建 mph-agent 分发包[/bold cyan]", border_style="cyan"))
    else:
        print("=" * 60)
        print("构建 mph-agent 分发包")
        print("=" * 60)
    
    # 清理旧的构建文件
    if console:
        with console.status("[cyan]清理旧的构建文件...", spinner="dots"):
            cleaned = _clean_build_files()
    else:
        print("\n1. 清理旧的构建文件...")
        cleaned = _clean_build_files()
    
    if cleaned:
        if console:
            console.print("  [green]✅[/green] 清理完成")
        else:
            print("  ✅ 清理完成")
    else:
        if console:
            console.print("  [dim]无需清理[/dim]")
        else:
            print("  无需清理")
    
    # 检查构建工具
    if console:
        with console.status("[cyan]检查构建工具...", spinner="dots"):
            _check_build_tools()
        console.print("  [green]✅[/green] 构建工具已就绪")
    else:
        print("\n2. 检查构建工具...")
        _check_build_tools()
        print("  ✅ 构建工具已就绪")
    
    # 构建分发包
    if console:
        console.print("\n[bold]3. 构建分发包...[/bold]")
    else:
        print("\n3. 构建分发包...")
    
    try:
        # 设置环境变量确保 UTF-8
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        if sys.platform != "win32":
            env["LANG"] = "en_US.UTF-8"
            env["LC_ALL"] = "en_US.UTF-8"
        
        # 使用进度条显示构建进度
        if console:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
                transient=True
            ) as progress:
                task = progress.add_task("[cyan]正在构建分发包...", total=100)
                
                # 在后台运行构建
                build_thread = threading.Thread(
                    target=_run_build,
                    args=(env, progress, task)
                )
                build_thread.daemon = True
                build_thread.start()
                build_thread.join(timeout=300)  # 5分钟超时
                
                if build_thread.is_alive():
                    progress.update(task, completed=100)
                    raise BuildTimeoutError("构建超时（超过 5 分钟）")
        else:
            # 简单模式：直接运行
            return_code, output = run_with_timeout(
                [sys.executable, "-m", "build"],
                timeout=300,
                env=env
            )
            if return_code != 0:
                # 只显示关键错误
                error_lines = [line for line in output.split('\n') if any(
                    keyword in line.lower() for keyword in ['error', 'failed', 'exception']
                )]
                if error_lines:
                    print("  关键错误信息:")
                    for line in error_lines[:5]:
                        print(f"    {line}")
                raise subprocess.CalledProcessError(return_code, "build", output)
        
        if console:
            console.print("  [green]✅ 构建成功！[/green]")
        else:
            print("  ✅ 构建成功！")
        
    except BuildTimeoutError as e:
        if console:
            console.print(f"  [red]❌ {e}[/red]")
        else:
            print(f"  ❌ {e}")
        return 1
    except subprocess.CalledProcessError as e:
        if console:
            console.print(f"  [red]❌ 构建失败[/red]")
            console.print(f"  错误代码: {e.returncode}")
        else:
            print(f"  ❌ 构建失败")
            print(f"  错误代码: {e.returncode}")
        return 1
    except KeyboardInterrupt:
        if console:
            console.print("\n  [yellow]⚠️  构建被用户中断[/yellow]")
        else:
            print("\n  ⚠️  构建被用户中断")
        return 1
    
    # 显示构建结果
    if console:
        console.print("\n[bold]4. 构建结果:[/bold]")
    else:
        print("\n4. 构建结果:")
    
    dist_dir = Path("dist")
    if dist_dir.exists():
        files = list(dist_dir.glob("*"))
        if files:
            for file in files:
                size_mb = file.stat().st_size / (1024 * 1024)
                if console:
                    console.print(f"  - [cyan]{file.name}[/cyan] ({size_mb:.2f} MB)")
                else:
                    print(f"  - {file.name} ({size_mb:.2f} MB)")
        else:
            if console:
                console.print("  [yellow]未找到构建文件[/yellow]")
            else:
                print("  未找到构建文件")
    else:
        if console:
            console.print("  [red]构建目录不存在[/red]")
        else:
            print("  构建目录不存在")
        return 1
    
    if console:
        console.print(Panel.fit("[bold green]构建完成！[/bold green]", border_style="green"))
        console.print("\n[bold]安装方式:[/bold]")
        console.print("  [cyan]pip install dist/mph_agent-*.whl[/cyan]")
        console.print("\n或安装到开发模式:")
        console.print("  [cyan]pip install -e .[/cyan]")
    else:
        print("\n" + "=" * 60)
        print("构建完成！")
        print("=" * 60)
        print("\n安装方式:")
        print("  pip install dist/mph_agent-*.whl")
        print("\n或安装到开发模式:")
        print("  pip install -e .")
    
    return 0


def _clean_build_files() -> bool:
    """清理旧的构建文件"""
    import shutil
    import glob
    
    cleaned = False
    for dir_name in ["build", "dist"]:
        dir_path = Path(dir_name)
        if dir_path.exists():
            shutil.rmtree(dir_path, ignore_errors=True)
            cleaned = True
    
    for path in glob.glob("*.egg-info"):
        if Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)
            cleaned = True
    
    return cleaned


def _check_build_tools():
    """检查构建工具"""
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "build", "wheel"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )


def _run_build(env: dict, progress, task):
    """在后台运行构建"""
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "build"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1
        )
        
        # 模拟进度更新
        progress.update(task, completed=10)
        
        # 读取输出但不显示（避免日志循环）
        last_update = time.time()
        start_time = time.time()
        timeout = 300  # 5分钟超时
        
        while process.poll() is None:
            # 检查超时
            if time.time() - start_time > timeout:
                process.terminate()
                time.sleep(1)
                if process.poll() is None:
                    process.kill()
                raise BuildTimeoutError(f"构建超时（超过 {timeout} 秒）")
            
            # 读取一行输出（非阻塞）
            try:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
            except Exception:
                break
            
            # 每 2 秒更新一次进度
            if time.time() - last_update > 2:
                current = progress.tasks[task].completed
                if current < 90:
                    progress.update(task, completed=min(current + 5, 90))
                last_update = time.time()
            
            time.sleep(0.1)
        
        # 等待进程完成
        return_code = process.wait()
        progress.update(task, completed=100)
        
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, "build")
            
    except BuildTimeoutError:
        progress.update(task, completed=100)
        raise
    except Exception as e:
        if process:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        progress.update(task, completed=100)
        raise


if __name__ == "__main__":
    sys.exit(build())
