<div align="center">
  <h1>Multiphysics Modeling Agent</h1>
  <p>把自然语言建模需求，变成可在 COMSOL 中打开的 <code>.mph</code> 文件</p>
  <p>
    <img src="https://img.shields.io/badge/mph--agent-1.1.2-green.svg" alt="mph-agent 1.1.2">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue.svg" alt="python >=3.10"></a>
    <img src="https://img.shields.io/badge/COMSOL-6.3-orange.svg" alt="COMSOL 6.3">
    <img src="https://img.shields.io/badge/Tauri-2.10.2-555555.svg" alt="Tauri 2.10.2">
    <img src="https://img.shields.io/badge/React-18.3.1-61DAFB.svg" alt="React 18.3.1">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="license MIT"></a>
    <img src="https://img.shields.io/badge/platform-Windows%20x64%20%7C%20macOS%20Apple%20Silicon-orange.svg" alt="platform Windows x64 | macOS Apple Silicon">
  </p>
  <p><b>中文</b> | English (coming soon)</p>
  <p>微信：<code>physicisthacker2030</code></p>
</div>

mph-agent 是面向 **COMSOL Multiphysics 6.3** 的开源建模智能体。在桌面应用里用自然语言描述几何、材料、物理场和研究，它会规划步骤、调用本机已授权的 COMSOL Java API，并按阶段写出可追踪的 `.mph`。

当前官方测试范围：**Windows x64**、**macOS Apple Silicon**。需要本机已安装正版 COMSOL 6.3，并配置一个 LLM 后端（DeepSeek、Kimi、Ollama 或 OpenAI 兼容接口）。

作者本科读应用物理，26 届转计算机，本项目是毕业设计选题实践的一部分。有交叉领域同好欢迎加微信闲聊。

## 重要声明

使用本软件即表示您已知晓并同意以下条款及 [LICENSE](LICENSE) 中的补充声明：

1. **本项目为独立开源工具，与 COMSOL 官方无任何关联，不是官方产品或插件。**
2. **仅通过 COMSOL 官方公开 API 做自动化调用，不包含 COMSOL 核心代码，不破解、不修改、不绕过许可。**
3. **使用前提是你已拥有合法、正版的 COMSOL Multiphysics 许可。**
4. **使用盗版或未授权 COMSOL 的法律责任由使用者自行承担。**
5. **仅用于学习、科研与合法合规的工程自动化。**

## 能做什么

- 用自然语言生成几何、材料、物理场、网格、研究和求解
- 讨论模式 `/discuss`、计划模式 `/plan`，确认后再执行
- 每个阶段单独保存 `.mph`，方便回看和排错
- 桌面应用配置 LLM、COMSOL 路径，并查看推理过程
- 技能库、案例库、本机 COMSOL 文档知识库（可选）

不提供 pip 包。日常使用请装桌面版，或从源码启动桌面应用。

## 安装

### 桌面版（推荐）

从 [GitHub Releases](https://github.com/iammm0/mph-agent/releases) 下载 `desktop-v*` 安装包：

- Windows x64：exe（NSIS）
- macOS Apple Silicon：dmg

安装包已内置 Java 11，不必再装 Python 或 JDK。暂不提供 Linux、Windows ARM、macOS Intel。

### 从源码运行

```bash
git clone https://github.com/iammm0/mph-agent.git
cd mph-agent
uv sync
uv run python cli.py
```

开发模式需要 [Node.js](https://nodejs.org/) 与 [Rust](https://rustup.rs/)。安装细节见 [docs/getting-started/INSTALL.md](docs/getting-started/INSTALL.md)。

## 配置

安装后配置 **LLM** 和 **COMSOL**（也可在桌面设置页填写）。在项目根目录复制 `env.example` 为 `.env`：

```env
LLM_BACKEND=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3
# Windows:
COMSOL_JAR_PATH=C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins
# macOS Apple Silicon:
# COMSOL_JAR_PATH=/Applications/COMSOL63/Multiphysics/plugins
```

`COMSOL_JAR_PATH` 也可留空，程序会尝试探测本机默认安装位置。输入 `/doctor` 可检查环境。更多后端见 [llm-backends.md](docs/getting-started/llm-backends.md)，配置项见 [CONFIG.md](docs/getting-started/CONFIG.md)。

可选：把本机 COMSOL 官方文档导入为本地知识库：

```bash
uv run python scripts/import_comsol_docs.py "C:\Program Files\COMSOL\COMSOL63\Multiphysics"
```

## 使用

```bash
uv run python cli.py
```

底部输入框直接描述建模需求即可。常用命令：`/plan`、`/run`、`/demo`、`/doctor`、`/help`。

源码下也可以这样调用：

```python
from agent.react.react_agent import ReActAgent

agent = ReActAgent(max_iterations=10)
path = agent.run("创建一个宽1米、高0.5米的矩形")
print(path)
```

更多例子见 [EXAMPLE.md](docs/getting-started/EXAMPLE.md)。

## 文档

- 安装与配置：[INSTALL.md](docs/getting-started/INSTALL.md)、[CONFIG.md](docs/getting-started/CONFIG.md)
- 文档索引：[docs/README.md](docs/README.md)
- 维护者说明：[AGENT.md](AGENT.md)

## 许可证

MIT License。详见 [LICENSE](LICENSE)。
