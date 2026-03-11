# Multiphysics Modeling Agent Desktop v0.1.0 — 首个版本发布说明

**发布日期**：2026 年 2 月  
**版本**：0.1.0  
**桌面端 Tag**：`desktop-v0.1.0`

---

## 概述

Multiphysics Modeling Agent（mph-agent）首个正式桌面版发布。通过自然语言描述建模需求，自动生成可在 COMSOL Multiphysics 中打开的 `.mph` 模型文件。本版本提供 **仅 Windows** 安装包，安装包内已包含 **Java 11**，无需单独安装 Python 或 JDK。**最终构建的安装程序会自行引用打包进去的 Java 11 环境**，其余行为与测试环境一致（不依赖系统 JAVA_HOME、不自动下载）。

---

## 下载与安装

### Windows 用户（推荐）

1. 打开 [GitHub Releases](https://github.com/iammm0/mph-agent/releases)，找到 **Multiphysics Modeling Agent Desktop v0.1.0**（或 tag `desktop-v0.1.0`）。
2. 在 **Assets** 中下载其一：
   - **`.exe`**（NSIS 安装程序）— 推荐
   - **`.msi`**（Windows Installer）
3. 运行安装程序，按提示完成安装。
4. 从开始菜单或桌面快捷方式启动 **Multiphysics Modeling Agent**。

### 系统要求

- **操作系统**：Windows 10/11（64 位）
- **COMSOL Multiphysics**：6.1 或更高（推荐 6.3+）
- **网络**：首次使用需配置 LLM 后端（API 或本地 Ollama），需联网
- **磁盘**：约 500 MB（含内嵌 Java 11）

无需单独安装 Python、JDK 或 Node.js。

---

## 主要功能

- **自然语言建模**：在输入框中用中文或英文描述几何、物理场、网格、研究等需求，Agent 自动规划并执行，生成 `.mph` 模型。
- **ReAct 推理**：支持多轮观察与迭代，提高复杂模型的生成成功率。
- **多 LLM 后端**：支持 DeepSeek、Kimi、Ollama、OpenAI 兼容等，在设置中配置 API Key 或 URL。
- **COMSOL 与 Java 配置**：在设置 → COMSOL 配置中通过 **「选择目录」** 在文件管理器里选择 COMSOL 的 `plugins` 目录及 Java 8/11 安装目录（可选，留空则使用安装包内嵌 Java 11），无需手动填写路径或改系统环境变量。
- **会话与记忆**：多会话、摘要式记忆，便于连续建模与偏好学习。
- **主题与界面**：支持浅色/深色主题与多种强调色。

---

## 首次使用必配项

安装并启动后，在应用内 **设置** 中完成：

1. **LLM 后端**（设置 → LLM 配置）：选择并配置至少一个（如 DeepSeek API Key、或本机 Ollama 地址）。
2. **COMSOL 与 Java**（设置 → COMSOL 配置）：点击 **「选择目录」** 在文件管理器中选取本机 COMSOL 的 `plugins` 目录（6.3+ 推荐）；如需使用自备的 Java 8 或 11，可再选择对应 JDK 安装目录，留空则使用安装包内嵌的 Java 11。

配置完成后即可在输入框输入建模需求开始使用。输入 **`/help`** 可查看斜杠命令，**`/doctor`** 可做环境诊断。

---

## 构建桌面安装包（维护者）

安装包需同时包含**前端、Python 后端（bridge）和 Java 11**，否则会出现 “Python bridge not initialized”。推荐在**项目根目录**执行一键脚本：

```powershell
# 项目根下执行
.\scripts\bundle-desktop.ps1
```

或：

```batch
scripts\bundle-desktop.bat
```

脚本会依次执行：

1. **build-bridge.ps1**：用 PyInstaller 将 Python 后端打成 `mph-agent-bridge-<target>.exe`，放到 `desktop/src-tauri/binaries/`。
2. **download-jdk11.ps1**：将 JDK 11 下载到 `desktop/src-tauri/resources/runtime/java`。
3. **npm run tauri build**：在 `desktop` 下打包 NSIS/MSI。

**环境要求**：已安装 Python（含项目依赖，如 `pip install -e .` 或 `uv sync`）、Node.js、Rust；PyInstaller 会在第一步自动安装。完成后安装包位于 `desktop/src-tauri/target/release/bundle/nsis` 与 `msi` 目录。

若在 `desktop` 目录下构建，也可直接执行 `npm run bundle`（内部会调用上述两个 PowerShell 脚本再执行 tauri build）。

---

## 已知限制

- **桌面端仅支持 Windows**：macOS 与 Linux 请使用 [从源码运行](https://github.com/iammm0/mph-agent#方式二从源码运行含桌面应用) 或 Python API。
- **依赖 COMSOL 本机安装**：需在本地已安装 COMSOL Multiphysics，Agent 通过其 Java API 生成模型。
- **LLM 需自行配置**：不包含内置大模型，需自备 API 或本地 Ollama 等。

---

## 文档与支持

- **安装与配置**：[INSTALL.md](../getting-started/INSTALL.md)、[CONFIG.md](../getting-started/CONFIG.md)
- **LLM 后端示例**：[llm-backends.md](../getting-started/llm-backends.md)
- **桌面 Bridge 调试**：出现「Bridge process closed unexpectedly」时见 [DEBUG-BRIDGE.md](../getting-started/DEBUG-BRIDGE.md)
- **项目主页**：[README](https://github.com/iammm0/mph-agent)
- **问题反馈**：[GitHub Issues](https://github.com/iammm0/mph-agent/issues)

---

## 开源协议

[MIT License](https://github.com/iammm0/mph-agent/blob/main/LICENSE)
