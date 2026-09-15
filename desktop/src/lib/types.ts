/** 消息角色 */
export type MessageRole = "user" | "assistant" | "system";

/** 助手消息专用展示形态（非 LLM 自由文本） */
export type AssistantPresentation = "environment_diagnosis";

/** 单条对话消息 */
export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  success?: boolean;
  events?: RunEvent[];
  /** 时间戳（可选，用于展示） */
  time?: number;
  /** 本次构建对应的模型路径（成功/失败/中止时均有，用于打开与预览） */
  modelPath?: string | null;
  caseData?: CaseGeneratedData | null;
  caseSavedPath?: string | null;
  /** 结构化 UI（如环境诊断卡片）；与 `text` 同源，由前端解析展示 */
  assistantPresentation?: AssistantPresentation;
}

/** 运行/流式事件（与后端 bridge-event 一致） */
export interface RunEvent {
  _event?: boolean;
  type: string;
  data?: Record<string, unknown>;
}

export type AgentMode = "discuss" | "plan" | "run";
export type AppView = "session" | "case-library" | "skills-system" | "ops-catalog" | "settings";

/** 对话框类型 */
export type DialogType =
  | null
  | "help"
  | "backend"
  | "context"
  | "exec"
  | "output"
  | "settings"
  | "ops"
  | "api"
  | "planQuestions";

/** 会话摘要 */
export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  groupId?: string | null;
}

export interface ConversationGroup {
  id: string;
  name: string;
  createdAt: number;
}

/** 后端 bridge_send 返回 */
export interface BridgeResponse {
  ok: boolean;
  message: string;
  /** 部分命令（如 list_models）返回的列表 */
  models?: MyComsolModel[];
  /** /run Plan 阶段已生成但需要澄清问题时为 true */
  plan_needs_clarification?: boolean;
  plan_confirmed?: boolean;
  plan?: Record<string, unknown> | null;
  clarifying_questions?: ClarifyingQuestion[];
  discussion_card?: Record<string, unknown> | null;
  case_generated?: Record<string, unknown> | null;
  saved_path?: string | null;
  items?: OpsCatalogItem[];
  total?: number;
  limit?: number;
  offset?: number;
  categories?: string[];
}

export interface CaseGlobalDefinition {
  name: string;
  value: string;
  unit?: string | null;
  description?: string | null;
}

export interface CaseSectionEntry {
  tag?: string;
  role?: string;
  type?: string;
  category?: string;
  purpose?: string;
  why?: string;
  quality_hint?: string;
  construction_clues?: string[];
  selection_hint?: string[];
  tree_clues?: string[];
}

export interface CaseWorkflowStep {
  stage?: string;
  action?: string;
  count?: number;
  targets?: string[];
}

export interface CaseGeneratedData {
  case_id?: string;
  source_model_path?: string;
  summary?: string;
  physical_principles?: string[];
  expected_behaviors?: string[];
  global_definitions?: CaseGlobalDefinition[];
  workflow_steps?: CaseWorkflowStep[];
  geometry_setup?: CaseSectionEntry[];
  material_setup?: CaseSectionEntry[];
  physics_setup?: CaseSectionEntry[];
  mesh_setup?: CaseSectionEntry[];
  study_setup?: CaseSectionEntry[];
  postprocess_setup?: CaseSectionEntry[];
  design_intent?: string[];
  recommended_edit_workflow?: string[];
  context_block?: string;
  copy_edit_prompt?: string;
  node_tree_excerpt?: string[];
  reusable_user_prompt?: string;
  extracted_at?: string;
}

/** 设置页「我创建的模型」列表项 */
export interface MyComsolModel {
  path: string;
  title: string;
  is_latest?: boolean;
}

/** 输入框「+」中的扩展功能项 */
export type PromptExtensionName =
  | "help"
  | "discuss"
  | "plan"
  | "run"
  | "case"
  | "ops"
  | "api"
  | "exec"
  | "backend"
  | "context"
  | "output"
  | "demo"
  | "doctor"
  | "exit";

export interface PromptExtensionItem {
  name: PromptExtensionName;
  label: string;
  description: string;
  icon: string;
}

export const PROMPT_EXTENSION_ITEMS: PromptExtensionItem[] = [
  { name: "help", label: "帮助", description: "打开帮助面板", icon: "message-question" },
  { name: "discuss", label: "切换到探讨", description: "切换到 Discuss，与 LLM 理清需求", icon: "message-bubble" },
  { name: "plan", label: "切换到规划", description: "切换到 Plan，生成建模计划与澄清", icon: "task-square" },
  { name: "run", label: "切换到执行", description: "切换到 Run，按需求调用 COMSOL 建模", icon: "play" },
  { name: "case", label: "读取 .mph 案例", description: "选择 .mph 文件并生成结构化案例摘要", icon: "document" },
  { name: "ops", label: "COMSOL 操作清单", description: "打开 COMSOL 可执行操作清单页", icon: "code-1" },
  {
    name: "api",
    label: "官方 API 浏览",
    description: "浏览/搜索已集成的 COMSOL 官方 API 包装",
    icon: "command-square",
  },
  { name: "exec", label: "JSON 执行", description: "根据 JSON 创建模型", icon: "document-code" },
  { name: "backend", label: "LLM 后端", description: "选择 LLM 后端", icon: "cpu" },
  { name: "context", label: "上下文", description: "查看或清除对话历史", icon: "clock" },
  { name: "output", label: "输出设置", description: "设置默认输出文件名", icon: "folder-2" },
  { name: "demo", label: "演示示例", description: "触发内置示例", icon: "flash" },
  { name: "doctor", label: "环境诊断", description: "执行环境检查", icon: "health" },
  { name: "exit", label: "退出程序", description: "关闭桌面应用", icon: "logout-01" },
];

/** 输入框「+」菜单：统一承载扩展功能入口 */
export const PROMPT_PLUS_MENU_COMMANDS: PromptExtensionItem[] = PROMPT_EXTENSION_ITEMS;

/** 工作模式切换（Discuss / Plan / Run） */
export const PROMPT_MODE_ITEMS: Array<{
  mode: AgentMode;
  label: string;
  title: string;
  icon: string;
}> = [
  { mode: "discuss", label: "探讨", title: "Discuss：与 LLM 理清需求（不执行 COMSOL）", icon: "message-bubble" },
  { mode: "plan", label: "规划", title: "Plan：生成建模计划与澄清", icon: "task-square" },
  { mode: "run", label: "执行", title: "Run：按需求或已确认计划调用 COMSOL 建模", icon: "play" },
];

/** 常用场景快捷提示（MessageList 空状态） */
export interface QuickPromptItem {
  label: string;
  text: string;
  extensionName?: PromptExtensionName;
}

export interface QuickPromptGroup {
  title: string;
  hint?: string;
  prompts: QuickPromptItem[];
}

export interface ClarifyingOption {
  id: string;
  label: string;
  value: string;
  /** 是否为推荐选项（前端可展示「推荐」标识） */
  recommended?: boolean;
}

export interface ClarifyingQuestion {
  id: string;
  text: string;
  source?: string;
  type: "single" | "multi";
  options: ClarifyingOption[];
}

export interface ClarifyingAnswer {
  question_id: string;
  selected_option_ids: string[];
  supplement_text?: string;
}

/** 新会话空状态：软件使用流程说明（与快捷案例并列展示） */
export interface UsageWorkflowStep {
  /** 步骤序号展示用 */
  step: number;
  title: string;
  /** 说明正文 */
  body: string;
}

export const USAGE_WORKFLOW_HEADLINE = "使用流程";
export const USAGE_WORKFLOW_INTRO =
  "本客户端通过「对话 + 模式切换」驱动 COMSOL 自动化建模；按下面顺序操作即可上手。";

export const USAGE_WORKFLOW_STEPS: UsageWorkflowStep[] = [
  {
    step: 1,
    title: "描述需求",
    body:
      "在底部输入框用自然语言写清物理场景：几何大致尺寸、材料、边界条件、关心的结果（温度、应力、流速等）。可随时补充约束。",
  },
  {
    step: 2,
    title: "选择工作方式（可自由组合）",
    body:
      "推荐：先切到探讨模式理清需求，再切到规划生成结构化计划，最后切到执行开始 COMSOL 建模。也可直接切到规划或执行；底部状态栏显示当前模式。",
  },
  {
    step: 3,
    title: "澄清与执行",
    body:
      "在 Plan 阶段若弹出澄清问题，先选择选项再继续；确认计划后切换到 Run 开始自动建模。执行中可用「停止」中断。",
  },
  {
    step: 4,
    title: "查看结果与文件",
    body:
      "对话区会展示推理与操作步骤；成功或结束后会给出模型文件路径。可在 + 菜单中打开输出设置，在设置里管理「我创建的模型」与打开目录。",
  },
  {
    step: 5,
    title: "扩展功能",
    body:
      "点击输入框左侧 + 可打开扩展功能，包括帮助、COMSOL 操作清单、官方 API、后端设置、环境诊断等。",
  },
];

/** 使用流程区可选一键打开的扩展功能（降低上手门槛） */
export const USAGE_WORKFLOW_SHORTCUTS: QuickPromptItem[] = [
  { label: "帮助", text: "", extensionName: "help" },
  { label: "环境诊断", text: "", extensionName: "doctor" },
  { label: "切换到规划", text: "", extensionName: "plan" },
];

/** 快捷提示：面向案例级 3D 多物理场模型的快捷构建指令 */
export const QUICK_PROMPT_GROUPS: QuickPromptGroup[] = [
  {
    title: "3D 热-结构（热应力）",
    hint: "类似案例库中的热-结构支架/夹具模型，一次性走完几何 + 材料 + 物理场 + 研究 + 求解 + 结果导出",
    prompts: [
      {
        label: "3D 支架热应力（完整流程）",
        text:
          "构建一个 3D 铝合金支架热-结构耦合模型：1）几何为 0.2 m × 0.1 m × 0.05 m 的带两个圆孔的支架实体；" +
          "2）材料采用铝合金（Aluminum），给出典型 E=70e9 Pa、nu=0.33、density=2700 kg/m^3、导热系数和比热；" +
          "3）添加固体传热（Heat Transfer in Solids）和固体力学（Solid Mechanics）物理场，并通过 Thermal Expansion 建立热应力耦合；" +
          "4）热边界条件：底面固定在 293.15 K，顶面对流换热（h=10 W/(m^2*K)，环境温度 293.15 K），在一个侧面施加恒定热通量 5000 W/m^2；" +
          "5）结构边界条件：底面固定约束，另一端面约束仅允许热膨胀方向自由；" +
          "6）生成适中网格（自由四面体，自动网格等级中等），配置稳态研究并求解热-结构耦合问题；" +
          "7）求解后创建一个显示温度场和一个显示等效应力（von Mises）的 3D 结果图，并导出温度场图像到 output/brace_T3D.png、应力云图到 output/brace_sigma3D.png。",
      },
    ],
  },
  {
    title: "3D 流体-传热（内部冷却）",
    hint: "类似“冷却通道/换热器”案例，一次性构建流体 + 传热耦合 3D 模型并导出结果",
    prompts: [
      {
        label: "3D 管道内部对流换热",
        text:
          "创建一个 3D 管道内部强制对流换热模型：1）几何为长度 1 m、内径 0.02 m 的圆柱形流道，外部包覆 0.005 m 厚的固体壁；" +
          "2）流体域为水（Water, 300 K），固体壁为钢或铜（给出典型导热系数和比热）；" +
          "3）在流体域添加单相流（Laminar Flow）和流体中的热传导（Conjugate Heat Transfer 或等效设置），固体域添加固体传热；" +
          "4）入口边界：速度入口 0.5 m/s，温度 293.15 K；出口边界：压力出口 0 Pa；外壁施加恒定温度 353.15 K；" +
          "5）生成适用于流体的网格（边界层 + 内部自由四面体，可简单近似），配置稳态共轭传热研究并求解；" +
          "6）求解后生成显示流体温度场和速度场的 3D 结果图，并导出温度场图像到 output/pipe_ctf_T3D.png。",
      },
    ],
  },
  {
    title: "3D 电磁-传热（线圈发热）",
    hint: "类似“感应线圈加热”或“电磁-热耦合”案例，包含电磁场 + 电阻发热 + 稳态传热",
    prompts: [
      {
        label: "3D 铜线圈电热耦合",
        text:
          "构建一个 3D 铜线圈电磁-热耦合模型：1）几何为若干匝的环形铜线圈，包围一个钢制被加热工件（可简化为圆柱或方块），外部为空气域；" +
          "2）线圈材料为铜（Copper），工件材料为钢（Steel），空气域为空气；" +
          "3）在铜线圈和工件区域添加电磁场物理（如 Electromagnetic Waves, Frequency Domain 或合适的静/准静场接口），并设置线圈驱动电流或电压，使线圈中产生电流和涡流损耗；" +
          "4）将电磁发热功率作为热源耦合到固体传热（Heat Transfer in Solids）中，在工件和线圈中求解温度场；" +
          "5）外表面与环境之间配置对流换热或恒定环境温度边界；" +
          "6）生成适合 3D 电磁-热问题的网格，配置稳态或频域-稳态耦合研究并求解；" +
          "7）求解后导出工件温度场的 3D 云图到 output/coil_heat_T3D.png。",
      },
    ],
  },
  {
    title: "3D 参数化传热（多工况）",
    hint: "类似“多孔散热器/散热片优化”案例，包含参数化扫描与结果导出",
    prompts: [
      {
        label: "3D 散热器参数化扫描",
        text:
          "构建一个 3D 散热器稳态传热参数化扫描模型：1）几何为一个 0.1 m × 0.1 m × 0.01 m 的基板，上方布置多排散热片（高度约 0.03 m，厚度和间距作为参数）；" +
          "2）材料采用铝（Aluminum）；" +
          "3）在基板底面施加均匀热通量 10000 W/m^2，上表面和散热片外表面与环境之间采用对流换热（h=20 W/(m^2*K)，环境 293.15 K）；" +
          "4）添加固体传热物理场，生成适中网格；" +
          "5）配置稳态研究，并添加参数化扫描：例如以散热片厚度或间距为参数，扫描 3~5 个取值；" +
          "6）求解完成后，导出每个参数工况下的最大温度或平均温度数据到 CSV 文件 output/heatsink_parametric.csv。",
      },
    ],
  },
  {
    title: "案例级作品（求解 + 结果导出）",
    hint: "目标是“像案例库作品一样”具备可复现输入、求解与可交付结果（图/数据）",
    prompts: [
      {
        label: "稳态传热（导出温度场图）",
        text: "做一个 2D 稳态传热案例：矩形板 0.2 m × 0.1 m，材料用铝（Aluminum）；左边界温度 373.15 K，右边界温度 293.15 K，上下边界绝热；生成网格，稳态求解；求解后导出温度场图像到 output/quickcase_heat_T.png（若需要可自动创建目录）。",
      },
    ],
  },
  {
    title: "诊断与工具",
    hint: "环境检查与帮助面板",
    prompts: [
      { label: "环境诊断", text: "", extensionName: "doctor" },
      { label: "帮助", text: "", extensionName: "help" },
    ],
  },
];

/** 动态 COMSOL 操作目录条目（操作清单页/弹窗） */
export interface OpsCatalogItem {
  category: string;
  label: string;
  invoke_mode: "native" | "wrapper";
  recommended_action: string;
  params_schema?: Record<string, unknown>;
  examples?: Array<Record<string, unknown>>;
}
