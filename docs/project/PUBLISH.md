# PyPI 打包与发布指南

> **说明**：本项目保留桌面端与源码运行，不再将 Python 包分发作为主要方式。以下内容仅供需要 PyPI 发布时参考。

本文档说明如何将 `mph-agent` 构建为 PyPI 包并通过 GitHub Actions 发布到 PyPI 或 Test PyPI。

## 工作流概览

- **工作流文件**：`.github/workflows/publish-pypi.yml`
- **触发方式**：
  1. **每次推送到 main**：向 `main` 分支 push 代码即触发构建并发布到 **PyPI**，版本为 `X.Y.Z.dev{运行号}`（如 `0.1.0.dev42`），保证每次提交都有唯一版本、不会 409。
  2. **发布正式版**：推送 tag（如 `v0.1.0`）或在 GitHub 创建 Release → 自动以 tag 版本发布到 **PyPI**，并创建 GitHub Release、附带构建产物。
  3. **手动运行**：Actions → “Publish to PyPI” → “Run workflow”（若工作流支持手动触发）。

## 本地构建（可选）

在本地验证打包是否成功：

```bash
pip install --upgrade build
python -m build
```

产物在 `dist/` 目录：`*.whl` 和 `*.tar.gz`。

## 配置 GitHub 与 PyPI

### 方式一：使用 API Token（推荐先使用）

1. **获取 PyPI API Token**
   - 登录 [pypi.org](https://pypi.org) → Account settings → API tokens → Add API token。
   - 创建 token，范围选 “Entire account” 或仅限当前项目。

2. **获取 Test PyPI API Token**
   - 登录 [test.pypi.org](https://test.pypi.org) → 同上创建 API token。

3. **在 GitHub 仓库中配置 Secret**
   - 仓库 → Settings → Secrets and variables → Actions。
   - 添加 Secret：
     - `PYPI_API_TOKEN`：PyPI 的 API token。
     - `TEST_PYPI_API_TOKEN`：Test PyPI 的 API token（仅需在发布到 Test PyPI 时使用）。

### 方式二：PyPI Trusted Publisher（更安全，可选）

使用 Trusted Publisher 后，无需在 GitHub 中保存 PyPI API token。

1. 在 PyPI 项目页 → Publishing → Add a new trusted publisher。
2. 按提示填写：
   - **Owner**：你的 GitHub 用户名或组织。
   - **Repository name**：`mph-agent`（或你的仓库名）。
   - **Workflow name**：`publish-pypi.yml`。
   - **Environment name**：留空或填 `pypi`（需与工作流中 `environment` 一致）。
3. 在工作流中若已配置 Trusted Publisher，可删除 `publish-pypi` job 里的 `with: password: ${{ secrets.PYPI_API_TOKEN }}`，仅保留 `id-token: write`。

## 发布流程

### 发布到 Test PyPI（测试）

1. 打开仓库 **Actions** 页。
2. 选择 **“Build and Publish to PyPI”**。
3. 点击 **“Run workflow”**，选择 **“testpypi”**，运行。
4. 安装测试：`pip install -i https://test.pypi.org/simple/ mph-agent`

### 发布到 PyPI（正式）

**方式 A：通过 Release 发布（推荐）**

1. 在 `pyproject.toml` 中确认 `version`（如 `0.1.0`）。
2. 提交并推送代码，在 GitHub 仓库中：Releases → Create a new release。
3. 选择或创建 tag（如 `v0.1.0`），填写 release 说明，发布。
4. 工作流会自动运行并将当前版本发布到 PyPI。

**方式 B：手动运行工作流**

1. Actions → “Build and Publish to PyPI” → “Run workflow”。
2. 选择 **“pypi”**，运行。
3. 当前 `pyproject.toml` 中的版本会被发布到 PyPI。

### 版本号约定

- **推送到 main**：CI 会自动使用 `pyproject.toml` 中的主版本（如 `0.1.0`）加上 `.dev{运行号}`（如 `0.1.0.dev42`）发布，无需改版本号。
- **打 tag 发布正式版**：在 `pyproject.toml` 中写好 `version`（如 `0.1.0`），然后推送 tag `v0.1.0`，CI 会以该版本发布；发布前请确认版本号已更新。
- 建议使用 [语义化版本](https://semver.org/lang/zh-CN/)（如 `0.1.0`、`0.2.0`、`1.0.0`）。  
- PyPI 不允许重复上传同一版本；每次 push 到 main 使用 dev 版本可避免 409。

## 故障排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 403 Forbidden | Token 无效或过期、或未配置 Secret | 检查 `PYPI_API_TOKEN` / `TEST_PYPI_API_TOKEN` 是否正确、是否在对应 Environment 可用 |
| 409 File already exists | 该版本已存在于 PyPI | 在 `pyproject.toml` 中提高 `version` 后重新发布 |
| 构建失败 | 依赖或 Python 版本不兼容 | 本地运行 `python -m build` 复现，检查 `requires-python` 与 `dependencies` |

更多细节见 [PyPI 帮助](https://pypi.org/help/) 与 [GitHub Actions 文档](https://docs.github.com/actions)。
