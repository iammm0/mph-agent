---
name: comsol-exceptions
description: COMSOL 常见 Exception/Error 的人类经验处理方式，供迭代时采纳
version: "1.0"
tags: [comsol, error, exception, FlException, 错误, 异常, 迭代]
triggers:
  - FlException
  - Exception
  - 已存在具有给定名称的对象
  - 具有给定名称的对象
  - 标记:
  - 未定义
  - 材料属性
  - 所需的
  - 求解失败
  - 特征遇到问题
  - error
  - 对象
---

## COMSOL 常见异常与处理方式

以下为人类经验总结，在因 error/exception 进入迭代时优先参考，用于调整计划或参数而非简单重试。

### 1. 已存在具有给定名称的对象（Duplicate name / 标记: mat1 等）

- **含义**：模型中已存在同名节点（如材料 mat1、物理场、研究等），再次创建同名会报错。
- **处理**：
  - **材料**：不要重复创建同名材料。若为“再次添加材料”场景，应使用**新名称**（如 mat2、mat_2）或在添加前先移除/重命名已有同名节点。当前系统若仅支持“创建新材料”，则修改 material_input 为使用新标识符（如“添加第二种材料，命名为 mat2”）。
  - **物理场/研究**：同理，使用新名称或先删除/重命名再创建。
- **可采纳的调整**：在 material_input / physics_input 等参数中明确“使用与现有不重名的名称（如 mat2、phys2）”，或回退到几何步后重新规划，确保每一步使用唯一标识符。

### 2. 未定义材料属性（如 nu、E）

- **含义**：线弹性/固体力学等物理场需要材料提供杨氏模量、泊松比等，未设置则报“未定义…所需的材料属性 nu”。
- **处理**：回退到 **add_material** 步骤，在 material_input 中**明确补充** youngsmodulus（E）与 poissonsratio（nu），例如“为线弹性材料补充 E=200e9 Pa，nu=0.3”。不要只写材料名而不写属性。
- **可采纳的调整**：modified_steps 中修改 step_id 为材料步，parameters.material_input 写清 E 和 nu 的数值与单位。

### 3. 特征遇到问题 / 求解失败（稳态求解器等）

- **含义**：多为前置设置不完整（缺材料属性、边界条件、网格等）导致求解器无法运行。
- **处理**：根据报错中的“特征”名称（如“线弹性材料 1”“稳态求解器 1”）判断缺的是材料还是物理场，回退到对应步骤补充参数，再重新执行后续步骤（材料 → 物理场 → 网格 → 研究 → 求解）。

### 4. 通用原则

- 遇到 Exception/Error 时**先识别类型**（重名 vs 缺属性 vs 其他），再决定是“改名称”“补参数”还是“回退到某步重做”。
- 同一错误若多次重试仍出现，应**改变策略**（例如换名称、补全参数），而不是重复相同操作。
- 若当前集成操作无法满足所需（例如需要“删除已有材料”“重命名节点”而系统无对应 API），应在最终总结中**建议集成哪些 COMSOL Java API 接口**（见下文）。

### 建议集成接口（当现有操作无法满足时）

以下接口**已集成**到 JavaAPIController，可直接使用或由执行器在后续扩展中调用：

1. **list_material_tags(model_path)** — 查询模型中现有材料节点名称列表  
2. **remove_material(model_path, name)** — 删除指定名称的材料节点  
3. **rename_material(model_path, old_name, new_name)** — 重命名材料节点（创建新名 + 复制后删旧）  
4. **has_material(model_path, name)** — 检查材料节点名称是否存在  
5. **update_material_properties(model_path, name, properties, property_group)** — 更新现有材料属性（不重新创建）  
6. **remove_all_materials(model_path)** — 批量删除所有材料节点  
7. **list_model_tree(model_path)** — 获取模型树（材料/物理场/研究/网格/几何 tags）  
8. **list_physics_tags / remove_physics / has_physics / rename_physics** — 物理场节点的查询/删除/存在检查/重命名  
9. **list_study_names / remove_study / rename_study / clear_study** — 研究节点的查询/删除/重命名/清空  
10. **generate_unique_physics_name(model_path, base)** / **generate_unique_study_name(model_path, base)** — 自动生成唯一节点名称  
11. **add_materials / add_physics / configure_study 内智能创建** — 若名称已存在则自动使用未占用名称（mat1→mat2、ht0→ht1、std1→std2），避免“已存在具有给定名称的对象”报错  

以上知识在错误反馈（observation.message / feedback）中出现对应关键词时注入，供 LLM 在 _rollback_and_inject 与 _llm_refine_plan 时采纳。
