# COMSOL Java API 使用笔记

## 基本使用

### 1. 创建模型

```java
import com.comsol.model.*;
import com.comsol.model.util.*;

Model model = ModelUtil.create("model_name");
```

### 2. 创建几何节点

```java
// 2D 几何
model.geom().create("geom1", 2);

// 3D 几何
model.geom().create("geom1", 3);
```

### 3. 创建几何形状

**重要**：矩形、圆、椭圆等是**几何节点（geom1）下的 feature**，不是单独的几何节点。应使用 `model.geom(geomName).create(featureName, type)` 创建，再用 `model.geom(geomName).feature(featureName).set(...)` 设置属性。

#### 矩形

```java
model.geom("geom1").create("rect1", "Rectangle");
model.geom("geom1").feature("rect1").set("size", new double[]{width, height});
model.geom("geom1").feature("rect1").set("pos", new double[]{x, y});
```

#### 圆形

```java
model.geom("geom1").create("circ1", "Circle");
model.geom("geom1").feature("circ1").set("r", radius);
model.geom("geom1").feature("circ1").set("pos", new double[]{x, y});
```

#### 椭圆

```java
model.geom("geom1").create("ell1", "Ellipse");
model.geom("geom1").feature("ell1").set("a", a);  // 长轴
model.geom("geom1").feature("ell1").set("b", b);  // 短轴
model.geom("geom1").feature("ell1").set("pos", new double[]{x, y});
```

### 4. 构建几何

```java
model.geom("geom1").run();
```

### 5. 保存模型

```java
model.save("output.mph");
```

## 完整示例

```java
import com.comsol.model.*;
import com.comsol.model.util.*;

public class Example {
    public static void main(String[] args) {
        try {
            // 创建模型
            Model model = ModelUtil.create("my_model");
            
            // 创建 2D 几何节点
            model.geom().create("geom1", 2);
            
            // 创建矩形（在 geom1 下创建 feature）
            model.geom("geom1").create("rect1", "Rectangle");
            model.geom("geom1").feature("rect1").set("size", new double[]{1.0, 0.5});
            model.geom("geom1").feature("rect1").set("pos", new double[]{0.0, 0.0});
            
            // 构建几何
            model.geom("geom1").run();
            
            // 保存模型
            model.save("output.mph");
            
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
```

## 常见问题

### Q: `UnsatisfiedLinkError: FlLicense.initWS0(...)` 从哪来？

**来源**：COMSOL 的 Java API 里部分功能（如许可证初始化 `FlLicense.initWS0`）通过 **JNI 调用本地库**（.dll / .so）实现。JVM 只在 **java.library.path** 和系统 PATH 里查找这些库；若未配置 COMSOL 的本地库目录，就会报 `UnsatisfiedLinkError`。

**处理**：

1. 为 JVM 设置 **java.library.path**，指向 COMSOL 安装目录下的 **bin / lib 子目录**（Windows：`Multiphysics\bin\win64`；macOS Apple Silicon：`Multiphysics/bin/macarm64` 与 `lib/macarm64`）。本仓库在启动 JVM 时会根据 `COMSOL_JAR_PATH` 自动推导该路径；若推导不对，可在 `.env` 中设置 **COMSOL_NATIVE_PATH** 为实际 bin 目录。
2. 或将 COMSOL 的 bin 目录加入系统 **PATH**，使 JVM 能加载到对应 .dll/.so。
3. 确认 COMSOL 许可证在无头/批处理模式下可用（若仅桌面授权，可能仍需在 GUI 环境下运行）。

### Q: 如何设置单位？
A: 默认单位为米（m），可通过模型设置更改。

### Q: 如何创建组合几何？
A: 使用布尔运算（Union, Difference, Intersection）。

### Q: 如何添加物理场？
A: 使用 `model.physics().create()` 方法。

### Q: 如何配置研究与求解？
A: 研究配置与求解通过 `model.study().create(studyName, studyType)` 创建研究、`model.study(studyName).run()` 运行求解。

## Python 封装（agent/executor/java_api_controller.py）

本仓库通过 Python 的 `JavaAPIController` 使用 jpype 直接调用官方 COMSOL Java API（`com.comsol.model.*`），不再维护自研 Java Builder 代码。

以下接口已在 `JavaAPIController` 中集成，可供 action_executor、迭代修复或后续扩展调用。

| 功能 | 方法 | 对应 Java API |
|------|------|----------------|
| 删除研究节点 | `remove_study(model_path, name)` | `model.study().remove("std1")` |
| 清空所有研究 | `clear_study(model_path)` | `model.study().remove(tag)` 逐项 |
| 查询研究名称 | `list_study_names(model_path)` | `model.study().names()` / `.tags()` |
| 重命名研究 | `rename_study(model_path, old_name, new_name)` | `model.study("std1").name("newName")` |
| 生成唯一研究名 | `generate_unique_study_name(model_path, base="std")` | 基于 list_study_names 找未占用名 |
| 检查节点是否存在 | `has_node(model_path, node_path)` | `model.hasNode("/studies/std1")` |
| 删除材料节点 | `remove_material(model_path, name)` | `model.material().remove("mat1")` |
| 查询材料名称 | `list_material_names(model_path)` / `list_material_tags(...)` | `model.material().names()` / `.tags()` |
| 删除物理场 | `remove_physics(model_path, name)` | `model.physics().remove("phys1")` |
| 查询物理场名称 | `list_physics_names(model_path)` / `list_physics_tags(...)` | `model.physics().names()` / `.tags()` |
| 生成唯一物理场名 | `generate_unique_physics_name(model_path, base="ht")` | 基于 list_physics_tags 找未占用名 |
| 更新材料属性 | `update_material_properties(model_path, name, properties, property_group)` | `model.material("mat1").propertyGroup("def").set("property", value)` |
| 清除所有结果 | `clear_all_results(model_path)` | `model.result().clearAll()` |
| 获取模型树结构 | `get_node_tree(model_path)` | `model.getNodeTree()`（不存在时回退到 list_model_tree） |
| 重命名几何 | `rename_geometry(model_path, old_name, new_name)` | `model.geom("geom1").name("newGeomName")` |
| 选择集创建 | `create_selection(model_path, tag, kind, geom_tag, entity_dim, entities, ...)` | `model.selection().create(tag, "Explicit")` + set |
| 选择集列表/删除/重命名 | `list_selection_tags` / `remove_selection` / `rename_selection` | `model.selection().tags()` / `.remove()` |
| 几何导入 | `import_geometry(model_path, file_path, geom_tag, feature_tag, ...)` | geom 下 Import 特征 + `run()` |
| 几何测量 | `geometry_measure(model_path, geom_tag, what, selection)` | `geom.measure().getVolume()` / `getArea()` / `getLength()` |
| 网格创建/列表/删除 | `mesh_create` / `mesh_list` / `mesh_remove` | `model.mesh().create(tag, geom_tag)` / `.tags()` / `.remove()` |
| 网格尺寸与统计 | `mesh_set_size(model_path, mesh_tag, hauto, hmax, ...)` / `mesh_stats(model_path, mesh_tag)` | Size 特征 `set("hauto", ...)`；mesh 统计 |
| 清除求解数据 | `clear_solution_data(model_path, solver_tag)` | `model.sol(tag).clearSolutionData()` |
| 导出结果图 | `export_plot_image(model_path, plot_group_tag, out_path, width, height, ...)` | `model.result().export().create("img1", "Image")` + set + run |
| 导出数据/表格 | `export_data(model_path, dataset_or_plot_tag, out_path, ...)` / `table_export(model_path, table_tag, out_path)` | result().export() / result().table().saveFile() |

此外还有：`list_model_tree`、`has_material`、`has_physics`、`rename_material`、`rename_physics`、`remove_all_materials`、`clear_physics`、`list_geometry_tags` 等。材料/物理场/研究/几何的列表统一兼容 `.names()` 与 `.tags()`。

上述能力中，`import_geometry`、`create_selection`、`export_plot_image`/`export_data`/`table_export` 已接入 ReAct 的 `ActionExecutor`（action：`import_geometry`、`create_selection`、`export_results`），步骤类型为 `geometry_io`、`selection`、`postprocess`；规划提示见 `agent/prompts/react/reasoning.txt`。单元测试见 `tests/test_schemas.py`（ExecutionStep 新 step_type）、`tests/test_react.py`（规划路径与执行器路由）。

## 参考资源

- **官方文档链接**：完整地址与版本说明见 [comsol-api-links.md](comsol-api-links.md)。
- COMSOL Multiphysics 用户指南
