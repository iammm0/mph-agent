# 上下文管理使用指南

## 概述

Multiphysics Modeling Agent（mph-agent）提供了上下文管理功能，可以：
- 记录每次对话的历史
- 自动生成上下文摘要
- 在后续对话中使用历史上下文信息
- 支持用户自定义命令别名

## 上下文功能

### 自动上下文记忆

每次在 TUI 中运行默认模式（输入自然语言生成模型）时，系统会自动：
1. 加载之前的对话历史
2. 提取用户偏好（常用单位、形状类型等）
3. 将上下文信息传递给 Planner Agent
4. 保存当前对话记录
5. 更新上下文摘要

### 查看上下文

在 TUI 中输入 **`/context`** 打开上下文对话框，可：

- 查看上下文摘要（默认）
- 查看统计信息
- 查看对话历史（含条数限制）

### 清除上下文

在 TUI 中打开 **`/context`**，选择清除对话历史。

### 禁用上下文

若不想使用上下文记忆，可在 TUI 的默认模式下使用（当前版本上下文默认启用；具体选项以 TUI 内说明为准）。

## 上下文存储位置

上下文数据存储在安装目录下的 `.context` 文件夹：
- `history.json` - 对话历史记录
- `summary.json` - 上下文摘要

## 自定义命令别名

### Linux/Mac

在 `~/.bashrc` 或 `~/.zshrc` 中添加：

```bash
alias ca="uv run python cli.py"
alias comsol="uv run python cli.py"
alias cagent="uv run python cli.py"
```

然后重新加载配置：`source ~/.bashrc` 或 `source ~/.zshrc`。

### Windows

在 PowerShell 配置文件中添加（`$PROFILE`）：

```powershell
function ca { uv run python cli.py @args }
function comsol { uv run python cli.py @args }
function cagent { uv run python cli.py @args }
```

### 使用示例

配置别名后：

```bash
ca          # 启动桌面应用
comsol      # 同上
```

## 上下文摘要内容

上下文摘要包含：
- 对话统计（总数、成功/失败次数）
- 最近使用的形状类型
- 用户偏好（常用单位等）
- 最近活动摘要

这些信息会在 Planner Agent 解析时自动使用，帮助更好地理解用户意图。

## 最佳实践

1. **定期查看上下文**：在 TUI 中使用 `/context` 查看统计与历史
2. **保持上下文清洁**：如果上下文过多，可以定期清除
3. **利用上下文**：让系统学习你的使用习惯，提高解析准确性
4. **自定义别名**：设置符合自己习惯的命令别名，提高效率
