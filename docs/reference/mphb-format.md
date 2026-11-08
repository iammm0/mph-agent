# `.mphb` 构建过程文件格式

`.mphb`（**MPH Build**）是 mph-agent 专用的「模型构建与操作过程」描述文件。它记录从用户需求到 `.mph` 模型生成的步骤时间线与操作日志，**需要 mph-agent 打开才能预览**；用普通编辑器打开只能看到带注释头的 JSON。

## 基本信息

| 项 | 值 |
|----|----|
| 扩展名 | `.mphb` |
| 根字段 `format` | `"mphb"` |
| 根字段 `kind` | `"com.sensorai.mph-agent.build"` |
| MIME | `application/vnd.mph-agent.build+json` |
| 当前 `format_version` | `1` |
| 步骤状态 | `pending` / `running` / `success` / `warning` / `skipped` / `failed`（读写时会把 `completed→success`、`error→failed`） |

安装桌面端后，系统会注册文件关联：双击 `.mphb` 会启动 mph-agent 并打开构建过程预览。

## 何时生成

- ReAct 运行结束（`RUN_END`）时，自动导出到当前任务的 `plans/` 目录（优先按模型 stem 命名，例如 `heat.mphb`）。
- 也可通过 Bridge 命令 `mphb_export` 手动导出。

## 预览入口

1. 运行成功后的助手消息卡片：「预览构建过程」
2. 侧边栏：「打开构建过程」
3. 资源管理器中双击 `.mphb`（已安装并关联后）

## 文档结构（摘要）

```json
{
  "format": "mphb",
  "format_version": 1,
  "kind": "com.sensorai.mph-agent.build",
  "generator": "mph-agent",
  "created_at": "ISO-8601",
  "title": "…",
  "user_input": "…",
  "success": true,
  "model_path": "…/xxx_latest.mph",
  "steps": [
    {
      "index": 1,
      "action": "create_geometry",
      "step_type": "geometry",
      "label": "几何建模",
      "status": "success",
      "message": "…",
      "model_path": "…/xxx_geometry.mph"
    }
  ],
  "operations": [
    { "time": "12:00:01", "step_type": "geometry", "message": "…", "result": "成功" }
  ]
}
```

文件开头可有以 `#` 开头的说明注释；解析时会自动跳过。

## 代码位置

| 模块 | 路径 |
|------|------|
| Schema | `agent/schemas/mphb.py` |
| 读写 / 组装 | `agent/utils/mphb_io.py` |
| 运行结束导出 | `ContextManager.export_mphb`、`react_agent` `RUN_END` |
| Bridge | `mphb_open` / `mphb_export` |
| 桌面预览 | `desktop/src/components/dialogs/MphbPreviewDialog.tsx` |
