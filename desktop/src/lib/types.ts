/** 消息角色 */
export type MessageRole = "user" | "assistant" | "system";

/** 单条对话消息 */
export interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  success?: boolean;
  events?: RunEvent[];
  /** 时间戳（可选，用于展示） */
  time?: number;
}

/** 运行/流式事件（与后端 bridge-event 一致） */
export interface RunEvent {
  _event?: boolean;
  type: string;
  data?: Record<string, unknown>;
}

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
}

/** 后端 bridge_send 返回 */
export interface BridgeResponse {
  ok: boolean;
  message: string;
  /** 部分命令（如 list_models）返回的列表 */
  models?: MyComsolModel[];
  /** /run Plan 阶段已生成但需要澄清问题时为 true */
  plan_needs_clarification?: boolean;
}

/** 设置页「我创建的模型」列表项 */
export interface MyComsolModel {
  path: string;
  title: string;
  is_latest?: boolean;
}

/** 斜杠命令项（Prompt 下拉用） */
export interface SlashCommandItem {
  name: string;
  display: string;
  description: string;
}

export const SLASH_COMMANDS: SlashCommandItem[] = [
  { name: "help", display: "/help", description: "显示帮助" },
  { name: "ops", display: "/ops", description: "支持的 COMSOL 操作" },
  { name: "api", display: "/api", description: "浏览/搜索已集成的 COMSOL 官方 API 包装" },
  { name: "run", display: "/run", description: "默认模式（自然语言 → 模型）" },
  { name: "plan", display: "/plan", description: "计划模式（自然语言 → JSON）" },
  { name: "exec", display: "/exec", description: "根据 JSON 创建模型" },
  { name: "backend", display: "/backend", description: "选择 LLM 后端" },
  { name: "context", display: "/context", description: "查看或清除对话历史" },
  { name: "output", display: "/output", description: "设置默认输出文件名" },
  { name: "demo", display: "/demo", description: "演示示例" },
  { name: "doctor", display: "/doctor", description: "环境诊断" },
  { name: "exit", display: "/exit", description: "退出" },
];

/** 常用场景快捷提示（MessageList 空状态） */
export interface QuickPromptItem {
  label: string;
  text: string;
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
}

export interface ClarifyingQuestion {
  id: string;
  text: string;
  type: "single" | "multi";
  options: ClarifyingOption[];
}

export interface ClarifyingAnswer {
  questionId: string;
  selectedOptionIds: string[];
}

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
    title: "诊断与命令",
    hint: "环境/帮助",
    prompts: [
      { label: "环境诊断", text: "/doctor" },
      { label: "帮助", text: "/help" },
    ],
  },
];

/** COMSOL 操作说明（/ops 弹窗） */
export interface ComsolOp {
  action: string;
  label: string;
  description: string;
}

export const COMSOL_OPS: ComsolOp[] = [
  { action: "geometry", label: "几何", description: "创建/编辑几何体与布尔运算" },
  { action: "physics", label: "物理场", description: "添加物理场与边界条件" },
  { action: "mesh", label: "网格", description: "划分网格" },
  { action: "study", label: "研究", description: "稳态/瞬态/特征值等研究" },
  { action: "material", label: "材料", description: "材料分配与属性" },
];
