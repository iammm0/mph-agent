---
name: comsol-materials
description: COMSOL 材料系统使用要点与经验
version: "1.0"
tags: [comsol, material, 材料, 属性, 密度, 导热, 杨氏模量]
triggers: [材料, material, 铜, 钢, 铝, 玻璃, 硅, 金, 银, 钛, 空气, 水, 密度, 导热系数, 杨氏模量, 泊松比, 比热, 电导率]
---

## COMSOL 材料系统要点

### 材料创建流程

1. `model.materials().create("mat1")` — 创建材料节点
2. `model.materials("mat1").label("Copper")` — 设置显示名
3. 设置属性或从内置库加载
4. `model.materials("mat1").selection().all()` — 分配到所有域，或用 `.set(new int[]{1,2})` 分配到指定域

### 内置材料库

COMSOL 提供丰富的内置材料，可直接引用：
- **Copper** — 铜
- **Steel AISI 4340** — 合金钢
- **Aluminum** — 铝
- **Glass (quartz)** — 石英玻璃
- **Silicon** — 硅
- **Gold** — 金
- **Silver** — 银
- **Titanium beta-21S** — 钛合金
- **Air** — 空气
- **Water** — 水

使用内置材料时设置 `builtin_name`，无需手动定义属性。

### 常用材料属性名 (COMSOL API propertyGroup("Def"))

| 属性名 | 说明 | 常见单位 |
|--------|------|---------|
| density | 密度 | kg/m³ |
| thermalconductivity | 导热系数 | W/(m·K) |
| specificheat | 比热 | J/(kg·K) |
| youngsmodulus | 杨氏模量 | Pa |
| poissonsratio | 泊松比 | — |
| electricconductivity | 电导率 | S/m |
| relpermittivity | 相对介电常数 | — |
| relpermeability | 相对磁导率 | — |
| dynamicviscosity | 动力粘度 | Pa·s |

### 材料分配规则

- **单材料模型**：用 `selection().all()` 分配到所有域。
- **多材料模型**：为每个材料指定 `domain_ids`，如 `selection().set(new int[]{1})` 将材料分配到域 1。
- 域 ID 从 1 开始，由几何构建顺序决定。
- 材料必须在物理场之前设置（部分物理场属性依赖材料参数）。

### 建模流程中的位置

正确顺序：**几何 → 材料 → 物理场 → 网格 → 研究 → 求解**

材料设置在几何之后、物理场之前，因为：
- 需要几何域存在才能分配材料
- 物理场边界条件可能依赖材料属性（如传热依赖导热系数）

### 常见场景

- **传热分析**：需设置 density、thermalconductivity、specificheat
- **结构分析 / 固体力学**：必须设置 density、youngsmodulus（E）、poissonsratio（nu）。线弹性材料默认「来自材料」，材料节点缺 `nu`/`E` 时求解会直接失败。
- **流体分析**：需设置 density、dynamicviscosity
- **电磁分析**：需设置 electricconductivity、relpermittivity、relpermeability
- 即使用内置材料库，结构场场景仍建议显式写上 E/nu，避免库加载失败或属性组不匹配。
