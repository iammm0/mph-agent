---
name: comsol-mph-postprocess
description: 用开源 MPh 做参数、求值与导出；多物理场建模仍走本仓库 Java API
version: "1.0"
tags: [comsol, mph, 后处理, 参数化, 导出, 求值, 验收, 多物理场]
triggers: [MPh, 导出, CSV, 求值, evaluate, 参数化, 扫描, 最大温度, 后处理, 验收]
---

## 职责边界

- **建模主链路**（几何/材料/物理场/网格/研究搭建）继续用本仓库 `JavaAPIController`。
- **开源 MPh**（https://github.com/MPh-py/MPh）只用于：读改全局参数、求解后表达式求值、CSV/数据导出、轻量验收。
- 安装：`uv sync --extra mph`；开关：`MPH_BACKEND=auto|on|off`。

## 推荐动作

1. **set_parameters** — `parameters={"t_fin":"0.002[m]","pitch":"0.005[m]"}`，改完再 `solve` 或继续扫描。
2. **evaluate_results** — `expression="maxop1(T)"`（或位移等）；没有表达式时做默认验收尝试。
3. **export_results** — `out_path` 以 `.csv` 结尾或 `export_type=data` 时优先走 MPh；失败自动回退 Java API。
4. 参数化扫描：先 **单点稳态** 收敛，再恢复多参数步；不要在残差不收敛时反复空建 study。

## 多物理场注意

- 耦合模型先保证每个物理场材料属性齐全（传热要 k，线弹性要 E/nu）。
- 对流/热通量边界缺失常表现为「找不到解 / 相对残差过大」，应回查物理场而不是只重建研究。
- 导出前确认存在对应结果节点/算子（如 maxop）；没有则先在研究后处理中建好再 evaluate。

## 何时不要用 MPh

- 创建几何、添加物理场特征、网格划分 → 仍用现有 ActionExecutor 步骤。
- 进程内 COMSOL client/JVM 冲突时，保持 `MPH_BACKEND=off`，导出走 Java API。
