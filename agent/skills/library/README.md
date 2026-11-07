# Skills 隐性知识库（skills_loader）

本目录存放 COMSOL 建模相关的**概念与经验**，以 Markdown 形式编写。Agent 在**推理**与**行动**时会通过 `SkillLoader` 加载、按 query 匹配或**向量检索**后注入到 LLM 的 prompt 中，作为可采纳的隐性知识。

## 目录结构

- 每个技能一个**子目录**，目录内必须包含 **`SKILL.md`**。
- `SKILL.md` 格式：YAML frontmatter（`---` 包裹） + Markdown 正文。
- Frontmatter 常用字段：
  - `name`: 技能唯一标识
  - `description`: 简短描述
  - `tags`: 标签列表，用于按主题匹配
  - `triggers`: 触发词列表，用户输入包含这些词时优先加载该技能
  - `version` / `author`: 可选

## 已包含技能

| 目录 | 说明 |
|------|------|
| `comsol-basics` | 几何建模要点：矩形/圆/椭圆参数、单位、顺序、命名与 JSON 规范 |
| `comsol-physics` | 物理场类型（传热/电磁/结构/流体）、边界条件、材料、稳态/瞬态 |
| `comsol-workflow` | 建模步骤顺序、研究类型、task_type 与 required_steps 规划、经验要点 |
| `comsol-mph-postprocess` | 可选接入开源 MPh：参数/求值/CSV 导出与求解验收；不替代建模主链路 |

## 持久化与向量检索（SQLite + sqlite-vec VSS）

- **持久化**：技能内容与向量索引存储在 **SQLite** 中，默认路径为项目根目录下 **`data/skills.db`**。
- **向量检索**：使用 **sqlite-vec** 扩展做 VSS（向量相似度检索），按 query 的语义检索最相关的知识片段，提高检索效率与上下文相关性。
- **依赖**：
  - 必选：`sqlite-vec`（已列入项目依赖）。
  - 可选：`pip install .[vec]` 安装 `sentence-transformers` 后，将自动对技能做嵌入并启用向量检索；未安装时仅使用 **triggers/tags** 关键词匹配，行为与之前一致。
- **首次使用**：若安装 `[vec]` 且 `data/skills.db` 中尚无数据，会在首次检索前自动对当前 `agent/skills/library/` 下的技能做一次索引。

## 加载与注入流程

1. **SkillLoader**（`agent/skills/loader.py`）：启动时扫描本目录（`agent/skills/library/`）下各子目录的 `SKILL.md`，解析 frontmatter 与正文，缓存为 `Skill` 对象。
2. **SkillVectorStore**（`agent/skills/vector_store.py`）：使用 SQLite + sqlite-vec 持久化技能并做向量检索；可选嵌入模型由 `get_default_embedder()` 提供（需安装 `[vec]`）。
3. **SkillInjector**（`agent/skills/injector.py`）：在每次调用 LLM 前，**优先**用向量检索按 query 取 Top-K 条知识；若无向量库或未命中则**回退**到 `triggers`/`tags` 匹配，将选中的 `instructions` 通过 `inject_into_prompt(query, prompt)` 拼接到 prompt 前部。
4. 使用注入的调用点：推理引擎（理解需求、改进计划）、几何/物理/研究 Planner、迭代控制器（改进计划）。

因此，在本目录中增改 `SKILL.md` 即可更新 Agent 可采纳的隐性知识；启用向量检索后，语义相近的 query 会命中更相关的技能，无需改代码。
