---
name: comsol-physics
description: COMSOL 物理场建模常用概念与经验
version: "2.0"
tags: [comsol, physics, 物理场, 传热, 电磁, 结构, 流体, 声学, 压电, 耦合]
triggers: [传热, 热, 温度, 电磁, 电场, 磁场, 结构, 力学, 流体, 物理场, 边界条件, 声学, 压电, 化学, 耦合, 多物理场]
---

## 物理场类型与 COMSOL 对应

| 类型 | COMSOL Tag | 说明 |
|------|-----------|------|
| heat | HeatTransfer | 传热 |
| electromagnetic | ElectromagneticWaves | 电磁波/AC-DC |
| structural | SolidMechanics | 结构力学 |
| fluid | SinglePhaseFlow | 单相流 |
| acoustics | Acoustics | 声学 |
| piezoelectric | Piezoelectric | 压电 |
| chemical | ChemicalSpeciesTransport | 化学物质传输 |
| multibody | MultibodyDynamics | 多体动力学 |

## 边界条件

每种物理场有不同的边界条件类型：

### 传热 (heat)
- **Temperature**：指定温度，参数 T0
- **HeatFlux**：热流密度，参数 q0；选择面用具体面 ID 列表
- **ConvectiveHeatFlux**：对流换热，参数 h（换热系数）、Text（环境温度）。实现上映射为 `HeatFluxBoundary` + `HeatFluxType=ConvectiveHeatFlux`；外表面可用 `selection: "all"`（必须真正调用 `selection().all()`）
- **Radiation**：辐射，参数 epsilon（发射率）
- **稳态可解性**：有热通量输入时必须有对流/温度边界把热量带走；仅有 HeatFlux、对流未挂上时，常见「找不到解 / 相对残差远大于容差」

### 结构力学 (structural)
- **FixedConstraint**：固定约束
- **BoundaryLoad**：边界载荷，参数 Fn（法向力）
- **Pressure**：压力，参数 p
- **Displacement**：位移约束

### 流体 (fluid)
- **InletVelocity**：入口速度，参数 U0
- **OutletPressure**：出口压力，参数 p0
- **Wall**：壁面（默认无滑移）

### 电磁 (electromagnetic)
- **PerfectElectricConductor**：完美电导体
- **SurfaceImpedance**：表面阻抗
- **Port**：端口

## 域条件

- **HeatSource**：热源，参数 Q0（体积热源功率密度）
- **BodyLoad**：体载荷，参数 Fx/Fy/Fz
- **VolumeForce**：体积力

## 初始条件

- 初始温度：变量 T，值如 293.15
- 初始位移：变量 u/v/w
- 初始速度：变量 u/v/w

## 多物理场耦合

- **thermal_stress**（热应力）：传热 + 结构力学
- **fluid_structure**（流固耦合）：流体 + 结构力学
- **electromagnetic_heat**（电磁热）：电磁 + 传热

耦合需在 `couplings` 中定义，指定参与的物理场接口。

## 常用概念

- **稳态 vs 瞬态**：稳态只求空间分布；瞬态需时间范围与步长。
- **边界条件**：先几何再物理场；边界条件施加在几何边界上（边或面）。
- **材料属性**：传热用导热系数、密度、比热；结构用杨氏模量、泊松比；流体用密度、粘度。
- **材料必须在物理场之前设置**。

## 规划输出约定

- 物理场计划 JSON 中 `fields` 为数组，每项含 `type`、`parameters`、`boundary_conditions`、`domain_conditions`、`initial_conditions`。
- `couplings` 为数组，每项含 `type` 和 `interfaces`。
- 用户只说"加物理场"且未指定类型时，默认使用 **heat（传热）**。
