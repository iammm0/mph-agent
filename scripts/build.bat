@echo off
REM 打包脚本 (Windows) - 带进度条和超时处理
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8

REM 超时时间（秒）
set BUILD_TIMEOUT=300

echo ============================================================
echo 构建 mph-agent 分发包
echo ============================================================

REM 清理旧的构建文件
echo.
echo 1. 清理旧的构建文件...
set CLEANED=0
if exist build (
    rmdir /s /q build 2>nul
    echo   已删除: build
    set CLEANED=1
)
if exist dist (
    rmdir /s /q dist 2>nul
    echo   已删除: dist
    set CLEANED=1
)
for /d %%d in (*.egg-info) do (
    rmdir /s /q "%%d" 2>nul
    echo   已删除: %%d
    set CLEANED=1
)
if !CLEANED!==0 (
    echo   无需清理
) else (
    echo   ✅ 清理完成
)

REM 检查构建工具
echo.
echo 2. 检查构建工具...
python -m pip install --upgrade build wheel --quiet >nul 2>&1
if errorlevel 1 (
    echo   ⚠️  构建工具安装可能有问题，继续尝试构建...
) else (
    echo   ✅ 构建工具已就绪
)

REM 构建分发包（带超时和进度显示）
echo.
echo 3. 构建分发包...
echo   正在构建，请稍候（最多等待 %BUILD_TIMEOUT% 秒）...
echo   进度: 

REM 启动构建进程
start /b python -m build > build_output.tmp 2>&1
set BUILD_START=%TIME%

REM 显示进度点并检查超时
set COUNTER=0
:BUILD_LOOP
timeout /t 2 /nobreak >nul 2>&1
set /a COUNTER+=2

REM 检查是否超时
if !COUNTER! gtr %BUILD_TIMEOUT% (
    echo.
    echo   ⚠️  构建超时，正在终止...
    taskkill /F /IM python.exe /FI "WINDOWTITLE eq *build*" >nul 2>&1
    del build_output.tmp 2>nul
    exit /b 1
)

REM 检查构建是否完成（通过检查输出文件）
if exist dist\*.whl (
    echo.
    echo   ✅ 构建成功！
    goto BUILD_DONE
)
if exist dist\*.tar.gz (
    echo.
    echo   ✅ 构建成功！
    goto BUILD_DONE
)

REM 检查构建进程是否还在运行
tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *build*" 2>nul | find /I "python.exe" >nul
if errorlevel 1 (
    REM 进程已结束，检查是否成功
    if exist dist (
        echo.
        echo   ✅ 构建成功！
        goto BUILD_DONE
    ) else (
        echo.
        echo   ❌ 构建失败
        if exist build_output.tmp (
            echo   关键错误信息:
            findstr /i "error failed exception" build_output.tmp | head -n 5
        )
        del build_output.tmp 2>nul
        exit /b 1
    )
)

echo|set /p="."
goto BUILD_LOOP

:BUILD_DONE
REM 等待构建完全完成
timeout /t 3 /nobreak >nul 2>&1

REM 检查构建是否真的成功
if not exist dist (
    echo.
    echo   ❌ 构建失败，未找到构建文件
    if exist build_output.tmp (
        echo   关键错误信息:
        findstr /i "error failed exception" build_output.tmp | head -n 5
    )
    del build_output.tmp 2>nul
    pause
    exit /b 1
)

REM 清理临时文件
del build_output.tmp 2>nul

REM 显示构建结果
echo.
echo 4. 构建结果:
for %%f in (dist\*) do (
    echo   - %%~nxf
)

echo.
echo ============================================================
echo 构建完成！
echo ============================================================
echo.
echo 安装方式:
echo   pip install dist\mph_agent-*.whl
echo.
echo 或安装到开发模式:
echo   pip install -e .

pause
