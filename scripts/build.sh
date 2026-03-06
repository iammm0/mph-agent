#!/bin/bash
# 打包脚本 (Linux/Mac) - 带进度条和超时处理

set -e

# 设置 UTF-8 编码
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONIOENCODING=utf-8

# 超时时间（秒）
BUILD_TIMEOUT=300

echo "============================================================"
echo "构建 mph-agent 分发包"
echo "============================================================"

# 清理旧的构建文件
echo ""
echo "1. 清理旧的构建文件..."
if [ -d "build" ] || [ -d "dist" ] || ls *.egg-info 2>/dev/null; then
    rm -rf build/ dist/ *.egg-info 2>/dev/null
    echo "  ✅ 清理完成"
else
    echo "  无需清理"
fi

# 检查构建工具
echo ""
echo "2. 检查构建工具..."
python -m pip install --upgrade build wheel --quiet >/dev/null 2>&1
echo "  ✅ 构建工具已就绪"

# 构建分发包（带超时和进度显示）
echo ""
echo "3. 构建分发包..."
echo "  正在构建，请稍候（最多等待 ${BUILD_TIMEOUT} 秒）..."

# 使用 timeout 命令设置超时（如果可用）
if command -v timeout >/dev/null 2>&1; then
    # Linux 系统使用 timeout 命令
    if timeout ${BUILD_TIMEOUT} python -m build > build_output.tmp 2>&1; then
        # 只显示关键信息
        if [ -f build_output.tmp ]; then
            grep -E "(Building|Creating|Successfully|error|Error|ERROR|failed|Failed)" build_output.tmp | head -n 10 | while IFS= read -r line; do
                echo "  → $line"
            done
            rm -f build_output.tmp
        fi
        echo "  ✅ 构建成功！"
    else
        BUILD_EXIT_CODE=$?
        echo "  ❌ 构建失败 (退出代码: $BUILD_EXIT_CODE)"
        if [ -f build_output.tmp ]; then
            echo "  关键错误信息:"
            grep -iE "(error|failed|exception)" build_output.tmp | head -n 5 | while IFS= read -r line; do
                echo "    $line"
            done
            rm -f build_output.tmp
        fi
        exit 1
    fi
else
    # Mac 系统可能没有 timeout，使用后台进程和进度显示
    python -m build > build_output.tmp 2>&1 &
    BUILD_PID=$!
    
    # 显示进度点
    (
        COUNTER=0
        while kill -0 $BUILD_PID 2>/dev/null && [ $COUNTER -lt $BUILD_TIMEOUT ]; do
            echo -n "."
            sleep 2
            COUNTER=$((COUNTER + 2))
        done
        echo ""
    ) &
    DOT_PID=$!
    
    # 等待构建完成
    if wait $BUILD_PID; then
        kill $DOT_PID 2>/dev/null 2>&1
        # 只显示关键信息
        if [ -f build_output.tmp ]; then
            grep -E "(Building|Creating|Successfully)" build_output.tmp | head -n 5 | while IFS= read -r line; do
                echo "  → $line"
            done
            rm -f build_output.tmp
        fi
        echo "  ✅ 构建成功！"
    else
        BUILD_EXIT_CODE=$?
        kill $DOT_PID 2>/dev/null 2>&1
        echo ""
        echo "  ❌ 构建失败 (退出代码: $BUILD_EXIT_CODE)"
        if [ -f build_output.tmp ]; then
            echo "  关键错误信息:"
            grep -iE "(error|failed|exception)" build_output.tmp | head -n 5 | while IFS= read -r line; do
                echo "    $line"
            done
            rm -f build_output.tmp
        fi
        exit 1
    fi
fi

# 显示构建结果
echo ""
echo "4. 构建结果:"
if [ -d "dist" ]; then
    ls -lh dist/ | tail -n +2 | awk '{print "  - " $9 " (" $5 ")"}'
else
    echo "  未找到构建文件"
    exit 1
fi

echo ""
echo "============================================================"
echo "构建完成！"
echo "============================================================"
echo ""
echo "安装方式:"
echo "  pip install dist/mph_agent-*.whl"
echo ""
echo "或安装到开发模式:"
echo "  pip install -e ."
