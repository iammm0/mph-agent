# 构建说明：最终安装程序

本文档说明如何在**项目根目录**下，将 **Python 桥接层 exe**、**前端桌面端**与**本地 Java 11** 一并构建进最终安装程序（NSIS/MSI）。

## 最终安装程序包含内容

| 组件 | 说明 | 构建产出位置 |
|------|------|--------------|
| Python 桥接层 | PyInstaller 打包的 `mph-agent-bridge.exe`（含 agent 与 bridge 逻辑） | `desktop/src-tauri/binaries/`，并被打包进安装程序 |
| 前端桌面端 | Tauri + React 桌面应用 | 安装程序主程序 + 前端资源 |
| 本地 Java 11 | 来自本地 `.venv/java11`（项目内置 JDK 11） | `desktop/src-tauri/resources/runtime/java`，并被打包进安装程序 |

安装包生成目录：`desktop/src-tauri/target/release/bundle/`（内含 `.exe` 安装程序与 `.msi`）。

---

## 前置条件

- **Windows**（当前仅支持 Windows 桌面安装包）
- **Python 3.8+**（建议使用 uv：<https://docs.astral.sh/uv/>）
- **Node.js LTS**（用于前端与 Tauri 构建）
- **Rust**（stable，用于 Tauri）
- **npm** 已安装（在 `desktop` 目录执行 `npm ci` 需可用）

---

## 一键构建（推荐）

在**项目根目录**执行：

```powershell
.\build-installer.ps1
```

该脚本会依次：

1. 构建桥接层 exe（`desktop/scripts/build-bridge.ps1`，依赖项目根目录）
2. 从本地 `.venv/java11` 拷贝 JDK 11 到 `desktop/src-tauri/resources/runtime/java`（若目标已存在则跳过）
3. 在 `desktop` 目录执行 `npm run tauri build`，生成安装程序

若执行策略限制 PowerShell 脚本，可先执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## 分步构建

若需分步执行或排查某一步，可按以下顺序在**项目根目录**进行。

### 步骤 1：构建 Python 桥接层 exe

桥接层由 PyInstaller 打包项目内 `bridge_entry.py` 及 agent 等模块，生成单文件 exe，供 Tauri 以 `externalBin` 形式打包进安装程序。

```powershell
# 必须在项目根目录执行（build-bridge.ps1 会切到根目录再调 PyInstaller）
.\desktop\scripts\build-bridge.ps1
```

- 产出：`dist/mph-agent-bridge.exe`，并复制到 `desktop/src-tauri/binaries/mph-agent-bridge-<target-triple>.exe`。

### 步骤 2：准备内置 Java 11

本项目在 `.venv/java11` 下已包含 JDK 11。构建安装程序时，需要把它拷贝到 Tauri 资源目录 `desktop/src-tauri/resources/runtime/java` 以便打包进安装程序。

- **推荐**：直接使用根目录的 `.\build-installer.ps1`（会自动完成拷贝）
- **如需单独执行**：运行 `desktop/scripts/download-jdk11.ps1`。该脚本会优先从项目根目录的 `.venv/java11` 拷贝；仅当本地不存在时才会回退到远程下载。

```powershell
cd desktop
.\scripts\download-jdk11.ps1
cd ..
```

- 产出：`desktop/src-tauri/resources/runtime/java/` 下完整 JDK 目录。

### 步骤 3：构建桌面端并生成安装程序

在 `desktop` 目录执行 Tauri 构建，会打包前端、桥接 exe 与 `resources/runtime/java`。

```powershell
cd desktop
npm run tauri build
cd ..
```

- 产出：`desktop/src-tauri/target/release/bundle/` 下的 NSIS 安装程序（.exe）与 MSI 包。

若希望一条命令完成步骤 1～3（在 desktop 内），可在 `desktop` 目录执行：

```powershell
cd desktop
npm run bundle
cd ..
```

注意：`npm run bundle` 会再次执行 `build-bridge.ps1`（需在项目根下调用才符合脚本预期），因此**推荐直接使用根目录的 `.\build-installer.ps1`**，由根目录统一驱动三步。

---

## 仅构建 Python 分发包（wheel/sdist）

若只需要 Python 包（不包含桌面安装程序），可在项目根目录执行：

```powershell
python -m build
# 或使用现有脚本
.\scripts\build.bat   # Windows
# 或
./scripts/build.sh    # Linux/macOS
```

产出在 `dist/` 下（如 `mph_agent-*.whl`）。这与「最终安装程序」相互独立。

---

## 目录与配置摘要

| 路径 | 用途 |
|------|------|
| `build-installer.ps1` | 根目录一键构建脚本（桥接 exe + Java 11 + Tauri 安装包） |
| `desktop/scripts/build-bridge.ps1` | 使用 PyInstaller 构建桥接 exe（需在项目根执行） |
| `desktop/scripts/bridge.spec` | PyInstaller spec，入口为根目录 `bridge_entry.py` |
| `desktop/scripts/download-jdk11.ps1` | 下载并解压 JDK 11 到 `desktop/src-tauri/resources/runtime/java` |
| `desktop/src-tauri/tauri.conf.json` | `externalBin`: 桥接 exe；`resources`: `resources/runtime/java` |
| `desktop/package.json` | `bundle` 脚本：build-bridge + download-jdk11 + tauri build |

---

## 常见问题

- **桥接层构建失败**：确认在**项目根目录**执行 `build-bridge.ps1`；Python 环境需能安装 `pyinstaller` 且能导入 `agent`、`jpype1` 等依赖。
- **JDK 11 下载失败**：检查网络与代理；脚本使用 Adoptium 官方接口，国内可考虑配置镜像或手动下载后解压到 `desktop/src-tauri/resources/runtime/java`。
- **Tauri 构建失败**：在 `desktop` 目录先执行 `npm ci`，确认 Rust 为 stable，再执行 `npm run tauri build`。
