# 安装和使用指南

本项目**保留桌面端与源码运行，不提供 Python 包分发**。请通过以下方式使用。

## 从源码运行

### 1. 安装依赖

在项目根目录执行：

```bash
uv sync
```

需先安装 [uv](https://docs.astral.sh/uv/)。

### 2. 启动

```bash
# 启动桌面应用（无参数即启动 Tauri 桌面端）
uv run python cli.py
```

无参数即启动桌面应用。若已构建过桌面端可执行文件，会优先运行本地可执行文件。

## 环境配置

安装后，需配置以下环境变量（**JAVA_HOME 为可选**，项目已集成 JDK 11）：

### 必需配置

1. **LLM 后端与 API Key** - 按所选后端配置其一（仅支持 deepseek / kimi / ollama / openai-compatible）
   - 使用 DeepSeek：`LLM_BACKEND=deepseek`，`DEEPSEEK_API_KEY=your_key`
   - 使用 Kimi：`LLM_BACKEND=kimi`，`KIMI_API_KEY=your_key`
   - 使用 Ollama：`LLM_BACKEND=ollama`（无需 API Key）
   - 使用中转 API：`LLM_BACKEND=openai-compatible`，`OPENAI_COMPATIBLE_API_KEY`、`OPENAI_COMPATIBLE_BASE_URL`
   ```bash
   # 示例：DeepSeek
   export LLM_BACKEND=deepseek
   export DEEPSEEK_API_KEY="your_api_key_here"
   ```

2. **COMSOL_JAR_PATH** - COMSOL JAR 文件路径或plugins目录
   ```bash
   # Linux/Mac (COMSOL 6.3+ 推荐使用plugins目录)
   export COMSOL_JAR_PATH="/opt/comsol63/multiphysics/plugins"
   
   # Windows (COMSOL 6.3+ 推荐使用plugins目录)
   set COMSOL_JAR_PATH=C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins
   
   # 也可以使用单个jar文件（COMSOL 6.1及更早版本）
   export COMSOL_JAR_PATH="/path/to/comsol.jar"
   ```
   
   **注意**：
   - COMSOL 6.3+ 版本推荐配置为 `plugins` 目录，程序会自动加载所有jar文件
   - COMSOL 6.1 及更早版本需要配置为单个jar文件路径

3. **JAVA_HOME** - 可选。不配置时使用**项目内置 JDK 11**（位于 `runtime/java`，首次使用 COMSOL 功能时自动下载）
   - 若需使用系统已安装的 Java，可配置：
   ```bash
   # Linux/Mac
   export JAVA_HOME="/usr/lib/jvm/java-11-openjdk"
   
   # Windows
   set JAVA_HOME=C:\Program Files\Java\jdk-17
   ```

### 可选配置

4. **JAVA_DOWNLOAD_MIRROR** - 内置 JDK 下载镜像，国内加速可设为 `tsinghua`（清华 TUNA）

5. **MODEL_OUTPUT_DIR** - 模型输出目录（默认为 **mph-agent 根目录下的 `models`**，该目录为唯一且首要；项目根目录上一级的 `models` 不再使用）
   ```bash
   # Linux/Mac
   export MODEL_OUTPUT_DIR="/path/to/output"
   
   # Windows
   set MODEL_OUTPUT_DIR=C:\path\to\output
   ```

### 使用 .env 文件（推荐）

在项目根目录或用户主目录创建 `.env` 文件：

```env
LLM_BACKEND=ollama
# 或 deepseek/kimi/openai-compatible，并配置对应 API Key
COMSOL_JAR_PATH=/path/to/comsol/plugins
# JAVA_HOME=  可选，不设则使用项目内置 JDK 11
MODEL_OUTPUT_DIR=/path/to/output
```

## 环境检查

安装和配置完成后，启动桌面应用，在底部输入 `/doctor` 进行环境检查。若所有检查通过，会显示通过信息；若有问题，会显示详细错误信息。

## 使用

### 基本使用

启动桌面应用后：

- **默认模式**：在底部输入自然语言建模需求（如「创建一个宽1米、高0.5米的矩形」），直接生成 COMSOL 模型
- **计划模式**：输入 `/plan` 切换为仅解析模式，下一句输入会解析为 JSON
- **斜杠命令**：`/demo`（演示）、`/doctor`（环境诊断）、`/context`（上下文摘要/历史/统计/清除）、`/backend`（选择 LLM 后端）、`/output`（设置默认输出文件名）、`/exec`（根据 JSON 创建模型或生成代码）、`/help`（帮助）

## 故障排除

### 问题 1: 环境变量未生效

**解决方案**：
- 使用 `.env` 文件（推荐）
- 确保环境变量在正确的 shell 中设置
- 重启终端或重新加载配置

### 问题 2: COMSOL JAR 文件找不到

**解决方案**：
- **COMSOL 6.3+ 版本**（推荐）：
  - Windows: `C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins`
  - Linux: `/opt/comsol63/multiphysics/plugins`
  - Mac: `/Applications/COMSOL63/Multiphysics/plugins`
  - 配置为plugins目录，程序会自动加载所有jar文件
- **COMSOL 6.1 及更早版本**：
  - Windows: `C:\Program Files\COMSOL\COMSOL61\Multiphysics\lib\win64\comsol.jar`
  - Linux: `/opt/comsol61/multiphysics/lib/glnxa64/comsol.jar`
  - Mac: `/Applications/COMSOL61/Multiphysics/lib/darwin64/comsol.jar`

### 问题 3: Java 环境错误

**解决方案**：
- 推荐不配置 `JAVA_HOME`，使用项目内置 JDK 11（首次使用 COMSOL 时自动下载到 `runtime/java`）
- 或确保已安装 JDK（不是 JRE），`JAVA_HOME` 指向正确路径，且版本与 COMSOL 兼容（通常 JDK 8-17）

### 问题 4: 桌面版支持哪些系统？

桌面应用**仅提供 Windows 安装包**（exe/msi），从 [GitHub Releases](https://github.com/iammm0/mph-agent/releases) 下载。暂不支持 macOS/Linux 桌面版。

### 问题 5: Windows 桌面应用构建报错 `linker link.exe not found` 或 `dlltool.exe not found`

**原因**：桌面应用（Tauri）使用 Rust 编译。  
- `link.exe not found`：当前为 MSVC 工具链，但未安装 Visual Studio 的 C++ 构建工具。  
- `dlltool.exe not found`：当前为 GNU 工具链（`x86_64-pc-windows-gnu`），但未安装 MinGW 的 binutils 或未加入 PATH。

**推荐：使用 MSVC 工具链**

1. 安装 [Build Tools for Visual Studio](https://visualstudio.microsoft.com/zh-hans/visual-cpp-build-tools/)，勾选工作负载 **「使用 C++ 的桌面开发」**。
2. 将 Rust 默认工具链设为 MSVC（若当前是 GNU）：
   ```bash
   rustup default stable-x86_64-pc-windows-msvc
   ```
3. 重新打开终端，再执行 `npm run tauri dev` 或 `uv run python cli.py`。

若已安装 Build Tools 但仍报 `link.exe not found`，可先打开 **「x64 本机工具命令提示」** 再编译。

**备选：继续使用 GNU 工具链**

若已安装 [MSYS2](https://www.msys2.org/) 且希望使用 GNU，需安装完整 MinGW 工具链并确保 `dlltool` 在 PATH 中：
   ```bash
   # 在 MSYS2 终端中
   pacman -S mingw-w64-x86_64-toolchain
   ```
   并将 MSYS2 的 `mingw64\bin`（如 `C:\msys64\mingw64\bin`）加入系统 PATH。

## 会话记忆与 Celery（可选）

桌面端支持**多会话**，每个会话对应一个物理模型构建上下文；后端会按会话维护**摘要式记忆**（最近对话、形状类型、偏好等），供后续推理时参考。

- **默认行为**：每次 run 结束后，记忆更新在**当前进程内同步执行**，无需额外服务。
- **可选：Celery 后台**：若希望将记忆更新放到后台进程执行，可安装可选依赖并启动 worker：
  1. 安装：`uv sync -e memory`（或 `pip install celery redis`）
  2. 启动 Redis（默认 `localhost:6379`）
  3. 启动 worker：`celery -A agent.core.celery_app worker -l info`
  此后 `do_run` 会优先将记忆更新任务投递到 Celery，由 worker 异步执行；未安装或未启动时自动回退为同步更新。

## 开发模式

在项目根目录执行 `uv sync` 后，修改代码会立即生效，无需重新安装。
