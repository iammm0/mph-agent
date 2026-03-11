# 配置说明

## 环境变量配置

创建 `.env` 文件（参考 `.env.example`），配置以下变量：

### 必需配置

#### 1. LLM 后端配置（仅支持 deepseek / kimi / ollama / openai-compatible）
- **DeepSeek**：`LLM_BACKEND=deepseek`，`DEEPSEEK_API_KEY=your_key`
- **Kimi**：`LLM_BACKEND=kimi`，`KIMI_API_KEY=your_key`
- **Ollama**：`LLM_BACKEND=ollama`（无需 API Key）
- **中转 API**：`LLM_BACKEND=openai-compatible`，`OPENAI_COMPATIBLE_API_KEY`、`OPENAI_COMPATIBLE_BASE_URL`

详见 [llm-backends.md](llm-backends.md)。

#### 2. COMSOL 配置
```bash
COMSOL_JAR_PATH=C:/Program Files/COMSOL/COMSOL63/Multiphysics/plugins
```

**重要说明**：
- 可以配置为 **plugins 目录**（推荐）：程序会自动加载目录下所有jar文件
- 也可以配置为单个jar文件路径（如果您的COMSOL版本有单独的comsol.jar）

**路径示例**：
- **Windows COMSOL 6.3+**（推荐）：`C:/Program Files/COMSOL/COMSOL63/Multiphysics/plugins`
- **Windows COMSOL 6.1**：`C:/Program Files/COMSOL/COMSOL61/Multiphysics/lib/win64/comsol.jar`
- **Linux COMSOL 6.3+**（推荐）：`/opt/comsol63/multiphysics/plugins`
- **Linux COMSOL 6.1**：`/opt/comsol61/multiphysics/lib/glnxa64/comsol.jar`
- **Mac COMSOL 6.3+**（推荐）：`/Applications/COMSOL63/Multiphysics/plugins`
- **Mac COMSOL 6.1**：`/Applications/COMSOL61/Multiphysics/lib/darwin64/comsol.jar`

#### 3. Java 配置（可选）
- **不配置**：使用项目内置 JDK 11（`runtime/java`，首次使用 COMSOL 时自动下载）
- **国内加速**：在 .env 中设置 `JAVA_DOWNLOAD_MIRROR=tsinghua` 使用清华镜像
- 若使用系统已安装的 Java，可配置：
```bash
JAVA_HOME=C:/Program Files/Java/jdk-17
```
- 确保 Java 版本与 COMSOL 兼容（通常 JDK 8-17）

### 可选配置

#### 模型输出目录
```bash
MODEL_OUTPUT_DIR=./models
```
- 默认值：**mph-agent 根目录下的 `models`**（唯一且首要的模型存放位置；项目根目录上一级的 `models` 不再使用）
- 模型文件（.mph）将保存在此目录

#### 日志级别
```bash
LOG_LEVEL=INFO
```
- 可选值：`DEBUG`, `INFO`, `WARNING`, `ERROR`
- 默认值：`INFO`

## 验证配置

运行环境诊断检查配置是否正确：

```bash
uv run python cli.py
```

在 TUI 内输入 `/doctor`。诊断会检查：
1. ✅ 配置文件完整性
2. ✅ COMSOL JAR 文件存在性
3. ✅ Java 环境配置
4. ✅ 输出目录可访问性
5. ✅ LLM 后端与 Python 依赖

## 常见配置问题

### 问题 1: COMSOL JAR 文件找不到

**解决方案**：
1. 确认 COMSOL 已正确安装
2. **对于 COMSOL 6.3 及以上版本**（推荐）：
   - 配置为 `plugins` 目录：`C:/Program Files/COMSOL/COMSOL63/Multiphysics/plugins`
   - 程序会自动加载目录下所有jar文件
3. **对于 COMSOL 6.1 及更早版本**：
   - 检查安装目录下的 `lib/` 文件夹
   - 根据操作系统选择正确的子目录：
     - Windows: `lib/win64/comsol.jar`
     - Linux: `lib/glnxa64/comsol.jar`
     - Mac: `lib/darwin64/comsol.jar`

### 问题 2: Java 环境错误

**解决方案**：
1. **推荐**：不配置 `JAVA_HOME`，使用项目内置 JDK 11（首次使用 COMSOL 功能时会自动下载到 `runtime/java`）
2. 或确认已安装 Java JDK（不是 JRE），设置 `JAVA_HOME` 指向 JDK 安装目录
3. 确保 Java 版本与 COMSOL 兼容（COMSOL 6.0+: JDK 8-17）

### 问题 3: API Key 无效

**解决方案**：
1. 确认 API Key 已正确复制（无多余空格）
2. 检查当前 LLM 后端对应的 API Key 是否有效（如 DeepSeek / Kimi 控制台）
3. 确认账户有足够的调用额度

## 配置示例

### Windows 完整配置示例（COMSOL 6.3+）
```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
COMSOL_JAR_PATH=C:/Program Files/COMSOL/COMSOL63/Multiphysics/plugins
JAVA_HOME=C:/Program Files/Java/jdk-17
MODEL_OUTPUT_DIR=./models
LOG_LEVEL=INFO
```

### Windows 完整配置示例（COMSOL 6.1）
```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
COMSOL_JAR_PATH=C:/Program Files/COMSOL/COMSOL61/Multiphysics/lib/win64/comsol.jar
JAVA_HOME=C:/Program Files/Java/jdk-17
MODEL_OUTPUT_DIR=./models
LOG_LEVEL=INFO
```

### Linux 完整配置示例（COMSOL 6.3+）
```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
COMSOL_JAR_PATH=/opt/comsol63/multiphysics/plugins
JAVA_HOME=/usr/lib/jvm/java-11-openjdk
MODEL_OUTPUT_DIR=./models
LOG_LEVEL=INFO
```

### Linux 完整配置示例（COMSOL 6.1）
```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
COMSOL_JAR_PATH=/opt/comsol61/multiphysics/lib/glnxa64/comsol.jar
JAVA_HOME=/usr/lib/jvm/java-11-openjdk
MODEL_OUTPUT_DIR=./models
LOG_LEVEL=INFO
```

### Mac 完整配置示例（COMSOL 6.3+）
```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
COMSOL_JAR_PATH=/Applications/COMSOL63/Multiphysics/plugins
JAVA_HOME=/Library/Java/JavaVirtualMachines/jdk-17.jdk/Contents/Home
MODEL_OUTPUT_DIR=./models
LOG_LEVEL=INFO
```

### Mac 完整配置示例（COMSOL 6.1）
```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx
COMSOL_JAR_PATH=/Applications/COMSOL61/Multiphysics/lib/darwin64/comsol.jar
JAVA_HOME=/Library/Java/JavaVirtualMachines/jdk-17.jdk/Contents/Home
MODEL_OUTPUT_DIR=./models
LOG_LEVEL=INFO
```
