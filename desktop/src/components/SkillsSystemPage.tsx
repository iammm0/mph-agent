import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import {
  createLocalSkillLibrary,
  fetchLocalSkillLibraries,
  fetchOnlineSkillLibrary,
  importLocalSkillLibrary,
  type LocalSkillLibraryItem,
  type OnlineSkillLibraryItem,
} from "../lib/skills";

type SkillPage = "overview" | "create" | "import" | "detail";
type SkillStatusTone = "success" | "error" | "neutral";
type SkillBadgeTone = "featured" | "installed" | "custom";

interface SkillNotice {
  tone: SkillStatusTone;
  text: string;
}

interface ShowcaseSkillItem {
  id: string;
  slug: string;
  name: string;
  description: string;
  summary: string;
  preview: string;
  tags: string[];
  triggers: string[];
  badgeText: string;
  badgeTone: SkillBadgeTone;
  categoryLabel: string;
  sourceLabel: string;
  origin: "local" | "online";
  path?: string;
  skillFile?: string;
  sourceUrl?: string;
  homepageUrl?: string;
  updatedAt?: string | null;
  author?: string;
  version?: string;
}

interface SkillDetailBlueprint {
  domain: string;
  focus: string;
  bestFor: string;
  deliverable: string;
  summary: string;
  modelingPath: string[];
  debuggingPath: string[];
  deliverables: string[];
  prompts: string[];
}

const FEATURED_SKILL_ORDER = [
  "comsol-basics",
  "comsol-3d",
  "comsol-materials",
  "comsol-physics",
  "comsol-workflow",
  "comsol-exceptions",
] as const;

function splitInput(value: string): string[] {
  return value
    .split(/[,，;\n；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const items: string[] = [];
  for (const value of values) {
    const text = value.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    items.push(text);
  }
  return items;
}

function pickSinglePath(value: string | string[] | null): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return typeof value[0] === "string" ? value[0] : "";
  return "";
}

const FEATURED_SKILL_DETAILS: Record<string, SkillDetailBlueprint> = {
  "comsol-basics": {
    domain: "基础规范",
    focus: "维度、单位、坐标和几何命名",
    bestFor: "需求刚澄清、模型准备开工时",
    deliverable: "不会跑偏的几何定义和基础建模约束",
    summary:
      "这类 skill 的核心不是多高级，而是先把维度、单位、坐标基准和几何拆解讲清楚。基础层一旦错，后面的材料、物理场和求解都会建立在错误模型上。",
    modelingPath: [
      "先判断模型是 2D 还是 3D，再决定可用的几何原语和布尔运算，不要在维度尚未明确时直接写操作步骤。",
      "把几何拆成最小可验证单元，例如外轮廓、孔洞、倒角前的主实体，优先保证主拓扑关系正确。",
      "统一单位和命名规范，尺寸、位置、模型名都保持短且稳定，避免后续参数引用混乱。",
      "当用户描述含糊时，先把默认位置、默认单位和几何顺序写清楚，再进入材料与物理场阶段。",
    ],
    debuggingPath: [
      "几何看起来不对，先查单位是否混用了 m 和 mm，再查 position 和 size 的参数顺序是否写反。",
      "2D/3D 操作报错时，先检查是否把 3D 原语放进了 2D 场景，或在 3D 中误用了二维布图思路。",
      "孔洞、差集、组合失败时，优先复核外轮廓和内轮廓的重叠关系，不要直接怀疑求解器。",
      "如果后续材料或物理场持续定位不到对象，通常不是后续步骤错，而是最初几何命名或域划分就不稳定。",
    ],
    deliverables: [
      "明确的维度判断和单位约定",
      "结构化几何拆解列表",
      "可复用的 shape / operation 命名方案",
      "进入后续材料与物理场前的几何检查清单",
    ],
    prompts: [
      "为一个带孔板件先整理几何原语、差集顺序和默认单位。",
      "把一个阶梯形零件拆成可执行的几何步骤，并指出每一步的命名规范。",
      "检查当前几何方案里哪些地方最容易造成 2D/3D 混用错误。",
    ],
  },
  "comsol-3d": {
    domain: "三维几何",
    focus: "3D 几何拆分、工作面和体操作",
    bestFor: "复杂实体、旋转体、拉伸体和装配结构",
    deliverable: "稳定的 3D 几何构建路径和体建模检查点",
    summary:
      "三维 skill 更关注实体如何拆分成可构建的原语组合，以及什么时候该用 WorkPlane、Extrude、Revolve、Difference 来降低几何复杂度。",
    modelingPath: [
      "先判断是原语堆叠、截面拉伸还是旋转体建模，别一开始就直接走最复杂的布尔组合。",
      "需要重复结构时，优先定义主基体，再补孔洞、通道、腔体和附属特征，减少布尔失败概率。",
      "涉及轴对称或轮廓驱动的结构，优先考虑 2D 截面 + Revolve；涉及挤出特征时优先用 WorkPlane + Extrude。",
      "3D 场景要同时考虑后续网格成本，几何阶段就要避免不必要的小特征和过细结构。",
    ],
    debuggingPath: [
      "拉伸或旋转后的实体方向不对时，先检查截面基准面和旋转轴，而不是盲目改尺寸。",
      "Difference 失败通常是实体没有真正相交，或切除体尺寸不足，先验证两个体的空间关系。",
      "模型运行很慢时，回头看几何是否引入了过多小尺度特征，3D 问题往往先从几何简化入手。",
      "求解前若域数量异常，优先检查 Union、Difference 后是否产生了意外分裂域或残留小体。",
    ],
    deliverables: [
      "3D 原语和体操作清单",
      "几何简化建议",
      "用于后续网格划分的结构风险提示",
      "适合三维问题的构建顺序说明",
    ],
    prompts: [
      "把一个散热器结构拆成基板、翅片、通孔和装配特征的 3D 建模路径。",
      "针对一个旋转体零件，说明何时应使用 2D 截面加 Revolve。",
      "检查当前三维管道模型里哪些布尔操作最可能失败。",
    ],
  },
  "comsol-materials": {
    domain: "材料系统",
    focus: "材料选型、属性完整性和域分配",
    bestFor: "传热、结构、电磁、流体等材料依赖问题",
    deliverable: "材料创建与属性补全策略",
    summary:
      "材料 skill 的关键不是列一堆材料名，而是识别当前物理场真正依赖哪些属性，决定用内置材料还是自定义参数，并把材料正确分配到目标域。",
    modelingPath: [
      "先根据物理场倒推必要属性，例如热问题需要导热系数、密度、比热，结构问题需要杨氏模量和泊松比。",
      "能用内置材料时优先用内置材料，减少属性缺漏；必须自定义时，再逐项列出关键属性和单位。",
      "多材料模型先确认域划分，再决定每个材料对应哪些 domain_ids，避免先配材料后发现域不可区分。",
      "材料步骤必须在物理场之前完成，尤其是耦合问题，很多边界和求解设置都会依赖材料属性。",
    ],
    debuggingPath: [
      "出现未定义材料属性时，不要直接重跑，先回退材料步骤补齐属性，再继续后续物理场和求解。",
      "结果明显异常时，检查是不是把材料分配到了错误域，尤其是多材料模型和布尔运算后的域重排。",
      "重复创建材料节点导致报错时，先看名称冲突，再决定使用新名称、更新属性或移除旧节点。",
      "参数数量看似齐全但数值不合理时，重点核查单位是否混用，特别是导热系数、模量、密度这三类高敏感属性。",
    ],
    deliverables: [
      "材料与域的映射关系",
      "每个物理场所需关键属性列表",
      "内置材料与自定义材料的选择建议",
      "材料缺失时的补参方案",
    ],
    prompts: [
      "为热应力模型整理材料属性清单，并指出哪些属性缺失会阻塞求解。",
      "给一个多域模型设计材料分配方案，并说明如何避免域映射错误。",
      "分析当前结构模型为什么会报缺少杨氏模量或泊松比。",
    ],
  },
  "comsol-physics": {
    domain: "物理场规划",
    focus: "物理接口选择、边界条件和耦合策略",
    bestFor: "单物理场搭建与多物理场组合",
    deliverable: "可执行的物理场配置思路",
    summary:
      "物理场 skill 的目标是先选对接口，再把边界、域条件、初始条件和耦合关系按模型拓扑落到位，避免一开始就陷入求解器层面的盲调。",
    modelingPath: [
      "先确定问题属于传热、结构、电磁、流体还是耦合问题，再选 COMSOL 中对应的接口，不要用模糊语言堆概念。",
      "把边界条件分成边界、域、初始三层来组织，确保每条条件都能落到具体几何对象上。",
      "多物理场问题先定义主接口，再定义耦合方式和参与接口，避免接口存在但耦合链路缺失。",
      "求解目标要和物理场配置同步考虑，例如稳态、瞬态、频域的边界和初始条件要求并不相同。",
    ],
    debuggingPath: [
      "结果发散或无意义时，优先检查边界条件是否欠约束、过约束，或施加到了错误边界上。",
      "耦合模型不工作时，先查接口名称和耦合关系，再查材料和几何域是否支持该耦合。",
      "如果一个物理场总提示缺参，通常不是求解器问题，而是材料属性或边界定义没闭合。",
      "求解前先做一轮边界条件盘点，确认入口、出口、固定约束、热源等关键条件没有遗漏。",
    ],
    deliverables: [
      "物理接口选型说明",
      "边界 / 域 / 初始条件清单",
      "多物理场耦合关系图",
      "与研究类型匹配的求解前检查项",
    ],
    prompts: [
      "为一个电磁热问题规划接口、边界条件和耦合顺序。",
      "审查当前流体模型是否存在边界条件欠约束。",
      "把热-结构耦合模型的关键前置条件列成执行清单。",
    ],
  },
  "comsol-workflow": {
    domain: "流程编排",
    focus: "几何到求解的完整执行顺序",
    bestFor: "全流程建模、研究配置和结果交付",
    deliverable: "可落地的建模流水线",
    summary:
      "workflow skill 负责把几何、材料、物理场、网格、研究、求解和结果导出串成稳定链路。它强调顺序正确、步骤完整、输出可交付。",
    modelingPath: [
      "先按几何 → 材料 → 物理场 → 网格 → 研究 → 求解的顺序组织任务，任何试图提前求解的方案都需要先质疑。",
      "根据用户目标判断 task_type，是只做几何、做到物理场，还是完整求解，不要默认所有任务都走 full。",
      "研究类型和输出目标一起设计，稳态、瞬态、频域、参数化扫描的输入信息完全不同。",
      "结果交付不能放到最后才想，建模阶段就要预留图像、表格、参数扫描结果等导出内容。",
    ],
    debuggingPath: [
      "流程卡住时，先检查是不是前置步骤缺失，例如没加材料就上物理场、没设研究就直接求解。",
      "求解耗时异常时，回头看网格是否过细、研究类型是否过重，而不是只盯着机器性能。",
      "输出文件不完整时，通常是结果节点或导出步骤没在流程里显式声明。",
      "任务边界不清时，先缩短流程，只验证到当前最关键的一步，再逐步扩展到完整闭环。",
    ],
    deliverables: [
      "完整步骤序列",
      "研究类型选择建议",
      "网格与求解开销提示",
      "结果导出和复核清单",
    ],
    prompts: [
      "把一个完整的热流耦合任务拆成可执行的 workflow 步骤。",
      "判断当前需求应该只做到 study 还是直接走 full 求解。",
      "为一个参数化散热器模型设计从建模到结果导出的流程。",
    ],
  },
  "comsol-exceptions": {
    domain: "异常排查",
    focus: "名称冲突、缺属性和求解失败的迭代处理",
    bestFor: "模型报错后的人类式调试",
    deliverable: "可复用的错误定位与回退策略",
    summary:
      "异常 skill 不负责美化报错，而是把错误拆成可定位、可回退、可修改的建模问题。目标是改变策略，而不是对相同错误反复重试。",
    modelingPath: [
      "先识别错误属于名称冲突、材料缺参、研究配置缺失还是求解器失败，再决定回退到哪一步。",
      "对名称冲突类问题，优先采用唯一命名策略；对属性缺失类问题，优先补参数而不是重复创建节点。",
      "把调试动作限定在最小闭环里，例如只重做材料步或研究步，不要每次都从头重建模型。",
      "当现有操作无法满足调试需求时，明确指出需要哪些 COMSOL Java API 能力支持。",
    ],
    debuggingPath: [
      "看到 duplicate name、标记冲突、对象已存在等字样时，优先检查节点命名而不是几何本体。",
      "看到未定义材料属性时，回退到材料步骤补全参数，再重新执行物理场与求解。",
      "求解失败但前面步骤没问题时，先核查研究类型、边界条件和网格，而不是直接调求解器参数。",
      "同一错误连续出现两次以上，要主动换策略，例如重命名、补参数、删除旧节点或缩小问题规模。",
    ],
    deliverables: [
      "错误类型归类",
      "建议回退到的步骤",
      "最小变更修复方案",
      "需要补充的接口能力清单",
    ],
    prompts: [
      "分析一次 duplicate name 报错，给出最小代价的修复方案。",
      "针对未定义材料属性的报错，说明应该回退到哪一步以及如何补参。",
      "把一次求解失败拆成网格、研究、边界和材料四条排查路径。",
    ],
  },
};

function buildGenericSkillDetail(skill: ShowcaseSkillItem): SkillDetailBlueprint {
  const domain = skill.tags.slice(0, 2).join(" / ") || "自定义领域";
  const firstTrigger = skill.triggers[0] ?? "当前任务";
  return {
    domain,
    focus: skill.tags.slice(0, 3).join("、") || "领域知识沉淀",
    bestFor: skill.triggers.length > 0 ? skill.triggers.slice(0, 3).join("、") : "新建领域规范",
    deliverable: "结构化的建模步骤、调试检查单和交付约束",
    summary:
      skill.description ||
      `${skill.name} 用来沉淀某个专业领域的建模经验。详情页默认给出通用建模路径和调试路径，你可以在对应 SKILL.md 中继续补充专有规则。`,
    modelingPath: [
      "先界定这个 skill 适用的对象、物理场和输出目标，避免把通用经验写成空泛描述。",
      "把领域知识拆成几何、材料、物理场、研究和结果交付几个阶段，逐段写清输入与约束。",
      "优先整理最容易重复使用的判断规则，例如单位、命名、边界条件默认值和结果导出格式。",
      `围绕“${firstTrigger}”构造一条最小可执行建模路径，确认 skill 能指导真实任务，而不是只停留在概念层。`,
    ],
    debuggingPath: [
      "先识别问题发生在几何、材料、物理场还是求解阶段，再决定回退范围。",
      "把常见错误整理成关键词和对应修复动作，避免每次调试都从零开始。",
      "对需要人工判断的步骤，加上复核项和停止条件，避免错误沿流程继续放大。",
      "当当前 skill 仍覆盖不了问题时，补充真实案例和失败样本，而不是继续堆空泛文字。",
    ],
    deliverables: [
      "适用边界与领域说明",
      "可执行的建模步骤模板",
      "常见错误与修复动作映射",
      "结果输出格式和复核要求",
    ],
    prompts: [
      `围绕“${firstTrigger}”补一版几何、材料、物理场和求解思路。`,
      `为 ${skill.name} 增加一个最常见报错的调试流程。`,
      `检查 ${skill.name} 里哪些规则还不够具体，需要继续补充。`,
    ],
  };
}

function buildLocalShowcaseSkill(
  local: LocalSkillLibraryItem,
  online?: OnlineSkillLibraryItem
): ShowcaseSkillItem {
  const isFeatured = FEATURED_SKILL_ORDER.includes(local.slug as (typeof FEATURED_SKILL_ORDER)[number]);
  const detail = FEATURED_SKILL_DETAILS[local.slug];
  return {
    id: local.slug,
    slug: local.slug,
    name: local.name,
    description: local.description || online?.description || "",
    summary: local.preview || local.description || online?.description || "暂无技能说明",
    preview: local.preview || local.description || "",
    tags: uniqueStrings([...local.tags, ...(online?.tags ?? [])]),
    triggers: local.triggers,
    badgeText: isFeatured ? "成品" : "自定义",
    badgeTone: isFeatured ? "installed" : "custom",
    categoryLabel: detail?.domain ?? "自定义领域",
    sourceLabel: local.path,
    origin: "local",
    path: local.path,
    skillFile: local.skillFile,
    sourceUrl: online?.sourceUrl,
    homepageUrl: online?.homepageUrl,
    updatedAt: local.updatedAt,
    author: local.author,
    version: local.version,
  };
}

function buildOnlineShowcaseSkill(online: OnlineSkillLibraryItem): ShowcaseSkillItem {
  const detail = FEATURED_SKILL_DETAILS[online.id];
  return {
    id: online.id,
    slug: online.id,
    name: online.name,
    description: online.description,
    summary: online.description || "暂无技能说明",
    preview: online.description || "",
    tags: online.tags,
    triggers: [],
    badgeText: online.installed ? "成品" : "推荐",
    badgeTone: online.installed ? "installed" : "featured",
    categoryLabel: detail?.domain ?? "在线领域",
    sourceLabel: online.provider,
    origin: "online",
    sourceUrl: online.sourceUrl,
    homepageUrl: online.homepageUrl,
  };
}

export function SkillsSystemPage() {
  const [page, setPage] = useState<SkillPage>("overview");
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);
  const [localSkills, setLocalSkills] = useState<LocalSkillLibraryItem[]>([]);
  const [onlineSkills, setOnlineSkills] = useState<OnlineSkillLibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"create" | "import" | null>(null);
  const [notice, setNotice] = useState<SkillNotice | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [triggersInput, setTriggersInput] = useState("");
  const [importSourcePath, setImportSourcePath] = useState("");

  const loadLibraries = useCallback(async () => {
    setLoading(true);
    const localResult = await fetchLocalSkillLibraries();
    const onlineResult = await fetchOnlineSkillLibrary();
    setLocalSkills(localResult.items);
    setOnlineSkills(onlineResult.items);
    if (!localResult.ok || !onlineResult.ok) {
      setNotice({
        tone: "error",
        text: !localResult.ok ? localResult.message : onlineResult.message,
      });
    }
    setLoading(false);
    return {
      ok: localResult.ok && onlineResult.ok,
      localResult,
      onlineResult,
    };
  }, []);

  useEffect(() => {
    void loadLibraries();
  }, [loadLibraries]);

  const showcaseSkills = useMemo(() => {
    const items: ShowcaseSkillItem[] = [];
    const localBySlug = new Map(localSkills.map((item) => [item.slug, item]));
    const onlineById = new Map(onlineSkills.map((item) => [item.id, item]));
    const seen = new Set<string>();

    for (const slug of FEATURED_SKILL_ORDER) {
      const local = localBySlug.get(slug);
      const online = onlineById.get(slug);
      if (local) {
        items.push(buildLocalShowcaseSkill(local, online));
        seen.add(slug);
        continue;
      }
      if (online) {
        items.push(buildOnlineShowcaseSkill(online));
        seen.add(slug);
      }
    }

    for (const local of localSkills) {
      if (seen.has(local.slug)) continue;
      items.push(buildLocalShowcaseSkill(local));
      seen.add(local.slug);
    }

    for (const online of onlineSkills) {
      if (seen.has(online.id)) continue;
      items.push(buildOnlineShowcaseSkill(online));
      seen.add(online.id);
    }

    return items;
  }, [localSkills, onlineSkills]);

  const selectedSkill = useMemo(() => {
    if (page !== "detail" || !selectedSkillId) return null;
    return showcaseSkills.find((item) => item.id === selectedSkillId || item.slug === selectedSkillId) ?? null;
  }, [page, selectedSkillId, showcaseSkills]);

  const selectedSkillDetail = useMemo(() => {
    if (!selectedSkill) return null;
    return FEATURED_SKILL_DETAILS[selectedSkill.slug] ?? buildGenericSkillDetail(selectedSkill);
  }, [selectedSkill]);

  const resetCreateForm = useCallback(() => {
    setName("");
    setDescription("");
    setTagsInput("");
    setTriggersInput("");
  }, []);

  const openSkillDetail = useCallback((skillId: string) => {
    setSelectedSkillId(skillId);
    setPage("detail");
  }, []);

  const goOverview = useCallback(() => {
    setPage("overview");
    setSelectedSkillId(null);
  }, []);

  const handleRefresh = useCallback(async () => {
    const result = await loadLibraries();
    if (result.ok) {
      setNotice({ tone: "success", text: "技能目录已刷新。" });
    }
  }, [loadLibraries]);

  const handleCreate = useCallback(async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setNotice({ tone: "error", text: "请先填写 skill 名称。" });
      return;
    }

    setBusy("create");
    try {
      const result = await createLocalSkillLibrary({
        name: trimmedName,
        description: description.trim(),
        tags: splitInput(tagsInput),
        triggers: splitInput(triggersInput),
      });
      if (!result.ok || !result.item) {
        setNotice({ tone: "error", text: result.message || "创建 skill 失败。" });
        return;
      }
      await loadLibraries();
      resetCreateForm();
      setNotice({ tone: "success", text: result.message || "Skill 已创建。" });
      openSkillDetail(result.item.slug);
    } finally {
      setBusy(null);
    }
  }, [description, loadLibraries, name, openSkillDetail, resetCreateForm, tagsInput, triggersInput]);

  const pickImportDirectory = useCallback(async () => {
    const selected = pickSinglePath(
      await open({
        directory: true,
        multiple: false,
        title: "选择要导入的技能目录",
      })
    );
    if (selected) {
      setImportSourcePath(selected);
    }
  }, []);

  const pickImportFile = useCallback(async () => {
    const selected = pickSinglePath(
      await open({
        directory: false,
        multiple: false,
        title: "选择要导入的 SKILL.md",
        filters: [{ name: "Skill Markdown", extensions: ["md"] }],
      })
    );
    if (selected) {
      setImportSourcePath(selected);
    }
  }, []);

  const handleImport = useCallback(async () => {
    const sourcePath = importSourcePath.trim();
    if (!sourcePath) {
      setNotice({ tone: "error", text: "请先选择或填写待导入的 skill 路径。" });
      return;
    }

    setBusy("import");
    try {
      const result = await importLocalSkillLibrary(sourcePath);
      if (!result.ok || !result.item) {
        setNotice({ tone: "error", text: result.message || "导入 skill 失败。" });
        return;
      }
      await loadLibraries();
      setImportSourcePath("");
      setNotice({ tone: "success", text: result.message || "Skill 已导入。" });
      openSkillDetail(result.item.slug);
    } finally {
      setBusy(null);
    }
  }, [importSourcePath, loadLibraries, openSkillDetail]);

  const openInFolder = useCallback((path: string) => {
    invoke("open_in_folder", { path }).catch(() => {
      if (navigator.clipboard?.writeText) {
        void navigator.clipboard.writeText(path);
      }
    });
  }, []);

  const openPath = useCallback((path: string) => {
    invoke("open_path", { path }).catch(() => {
      if (navigator.clipboard?.writeText) {
        void navigator.clipboard.writeText(path);
      }
    });
  }, []);

  const openRemote = useCallback((url: string) => {
    window.open(url, "_blank", "noopener,noreferrer");
  }, []);

  const totalSkillCount = showcaseSkills.length;

  const pageTitle =
    page === "overview"
      ? "技能系统"
      : page === "create"
        ? "创建 Skill"
        : page === "import"
          ? "导入 Skill"
          : selectedSkill?.name ?? "Skill 详情";

  const pageDesc =
    page === "overview"
      ? `前两张卡片是创建与导入入口，其余 ${totalSkillCount} 张卡片都是成品 skill，可直接进入对应领域的建模与调试详情页。`
      : page === "create"
        ? "把新的领域经验沉淀成 skill 模板。"
        : page === "import"
          ? "把已有的 skill 目录接入当前项目。"
          : selectedSkillDetail?.summary ?? "查看某个 skill 的建模与调试思路。";

  const renderOverview = () => (
    <div className="skills-stage">
      <div className="skills-showcase-grid">
        <button
          type="button"
          className="skills-showcase-tile skills-showcase-tile--action skills-showcase-tile--create"
          onClick={() => setPage("create")}
        >
          <div className="skills-showcase-plus" aria-hidden>
            +
          </div>
          <div className="skills-showcase-body">
            <span className="skills-showcase-label">新入口</span>
            <h3 className="skills-showcase-title">创建 Skill</h3>
            <p className="skills-showcase-summary">新建一个技能模板，并把你的建模方法沉淀成可复用规则。</p>
          </div>
          <div className="skills-showcase-footer">进入创建页</div>
        </button>

        <button
          type="button"
          className="skills-showcase-tile skills-showcase-tile--action skills-showcase-tile--import"
          onClick={() => setPage("import")}
        >
          <div className="skills-showcase-plus" aria-hidden>
            +
          </div>
          <div className="skills-showcase-body">
            <span className="skills-showcase-label">新入口</span>
            <h3 className="skills-showcase-title">导入 Skill</h3>
            <p className="skills-showcase-summary">把已有的 skill 目录或单个 SKILL.md 接入当前项目的技能系统。</p>
          </div>
          <div className="skills-showcase-footer">进入导入页</div>
        </button>

        {showcaseSkills.map((item) => (
          <button
            key={item.id}
            type="button"
            className="skills-showcase-tile"
            onClick={() => openSkillDetail(item.id)}
          >
            <div className="skills-showcase-body">
              <h3 className="skills-showcase-title">{item.name}</h3>
              <p className="skills-showcase-summary">{item.description || item.summary}</p>
            </div>
            {item.triggers.length > 0 ? (
              <div className="skill-card-tags">
                {item.triggers.slice(0, 3).map((tag) => (
                  <span key={`${item.id}-${tag}`} className="skill-card-tag">
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </button>
        ))}

        {!loading && showcaseSkills.length === 0 && (
          <div className="skills-empty skills-empty--stage">当前还没有可展示的 skill，请先创建或导入。</div>
        )}
      </div>
    </div>
  );

  const renderCreatePage = () => (
    <div className="skills-stage">
      <section className="skills-page-card">
        <div className="skills-page-card-head">
          <div>
            <span className="skills-page-kicker">Create</span>
            <h3 className="skills-page-title">创建新的 Skill</h3>
            <p className="skills-page-desc">
              这里负责具体的创建逻辑。填写名称、领域说明、标签和触发词后，系统会在项目的
              <code> agent/skills/library/ </code>
              目录下生成新的技能模板。
            </p>
          </div>
        </div>
        <div className="skills-workspace-grid">
          <form
            className="skills-editor"
            onSubmit={(event) => {
              event.preventDefault();
              void handleCreate();
            }}
          >
            <label className="skills-field">
              <span>Skill 名称</span>
              <input
                className="dialog-input"
                type="text"
                placeholder="例如：热管理设计规范"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="skills-field">
              <span>领域说明</span>
              <textarea
                className="dialog-input skills-textarea"
                placeholder="说明这个 skill 主要覆盖哪一类建模问题、约束和输出。"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <label className="skills-field">
              <span>标签</span>
              <input
                className="dialog-input"
                type="text"
                placeholder="逗号分隔，例如：comsol, heat, workflow"
                value={tagsInput}
                onChange={(event) => setTagsInput(event.target.value)}
              />
            </label>
            <label className="skills-field">
              <span>触发词</span>
              <input
                className="dialog-input"
                type="text"
                placeholder="逗号分隔，例如：散热器, 热应力, 温度场"
                value={triggersInput}
                onChange={(event) => setTriggersInput(event.target.value)}
              />
            </label>
            <div className="skills-page-actions">
              <button type="submit" className="dialog-btn primary" disabled={busy !== null}>
                {busy === "create" ? "创建中..." : "创建 Skill"}
              </button>
              <button type="button" className="dialog-btn secondary" onClick={goOverview} disabled={busy !== null}>
                返回技能广场
              </button>
            </div>
          </form>

          <aside className="skills-side-note">
            <h4>推荐写法</h4>
            <ul className="skills-checklist">
              <li>先界定这个 skill 解决的建模对象，再写求解或调试方法。</li>
              <li>标签用于聚类领域，触发词用于命中用户需求，二者不要完全重复。</li>
              <li>描述里最好写清默认单位、典型物理场和需要输出的结果。</li>
              <li>如果后续要做成品详情页，优先补充建模路径、调试路径和交付物。</li>
            </ul>
          </aside>
        </div>
      </section>
    </div>
  );

  const renderImportPage = () => (
    <div className="skills-stage">
      <section className="skills-page-card">
        <div className="skills-page-card-head">
          <div>
            <span className="skills-page-kicker">Import</span>
            <h3 className="skills-page-title">导入已有 Skill</h3>
            <p className="skills-page-desc">
              这里负责具体的导入逻辑。你可以选择一个包含 <code>SKILL.md</code> 的目录，也可以直接粘贴
              <code>SKILL.md</code> 文件路径。
            </p>
          </div>
        </div>
        <div className="skills-workspace-grid">
          <div className="skills-editor">
            <label className="skills-field">
              <span>待导入路径</span>
              <input
                className="dialog-input"
                type="text"
                placeholder="选择目录，或粘贴某个 SKILL.md 的绝对路径"
                value={importSourcePath}
                onChange={(event) => setImportSourcePath(event.target.value)}
              />
            </label>
            <div className="skills-import-actions">
              <button type="button" className="dialog-btn secondary" onClick={() => void pickImportDirectory()}>
                选择目录
              </button>
              <button type="button" className="dialog-btn secondary" onClick={() => void pickImportFile()}>
                选择 SKILL.md
              </button>
            </div>
            <div className="skills-import-preview">
              <span className="skills-import-preview__label">当前路径</span>
              <div className="skills-import-preview__value">{importSourcePath || "尚未选择任何路径"}</div>
            </div>
            <div className="skills-page-actions">
              <button
                type="button"
                className="dialog-btn primary"
                onClick={() => void handleImport()}
                disabled={busy !== null}
              >
                {busy === "import" ? "导入中..." : "导入 Skill"}
              </button>
              <button type="button" className="dialog-btn secondary" onClick={goOverview} disabled={busy !== null}>
                返回技能广场
              </button>
            </div>
          </div>

          <aside className="skills-side-note">
            <h4>导入前检查</h4>
            <ul className="skills-checklist">
              <li>目录内至少要有一个 <code>SKILL.md</code>。</li>
              <li>如果是单文件导入，建议文件名直接使用 <code>SKILL.md</code>。</li>
              <li>导入后会复制到项目的 <code>agent/skills/library/</code> 目录，并出现在技能广场。</li>
              <li>导入成功后建议立即补齐详情页中的建模路径和调试路径内容。</li>
            </ul>
          </aside>
        </div>
      </section>
    </div>
  );

  const renderDetailPage = () => {
    if (loading && !selectedSkill) {
      return (
        <div className="skills-stage">
          <div className="skills-empty skills-empty--stage">正在加载 skill 详情...</div>
        </div>
      );
    }

    if (!selectedSkill || !selectedSkillDetail) {
      return (
        <div className="skills-stage">
          <div className="skills-empty skills-empty--stage">
            当前 skill 不存在或尚未同步完成。
            <div className="skills-page-actions">
              <button type="button" className="dialog-btn secondary" onClick={goOverview}>
                返回技能广场
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="skills-stage">
        <section className="skills-detail-hero">
          <div className="skills-detail-hero__head">
            <div>
              <h3 className="skills-page-title">{selectedSkill.name}</h3>
              <p className="skills-page-desc">
                {selectedSkill.description || selectedSkillDetail.summary}
              </p>
            </div>
          </div>

          {selectedSkill.triggers.length > 0 ? (
            <div className="skill-card-tags">
              {selectedSkill.triggers.map((tag) => (
                <span key={`${selectedSkill.id}-trigger-${tag}`} className="skill-card-tag">
                  {tag}
                </span>
              ))}
            </div>
          ) : null}

          <div className="skills-page-actions">
            {selectedSkill.path && (
              <button type="button" className="dialog-btn secondary" onClick={() => openInFolder(selectedSkill.path!)}>
                打开目录
              </button>
            )}
            {selectedSkill.skillFile && (
              <button type="button" className="dialog-btn secondary" onClick={() => openPath(selectedSkill.skillFile!)}>
                打开 SKILL.md
              </button>
            )}
            {selectedSkill.sourceUrl && (
              <button type="button" className="dialog-btn secondary" onClick={() => openRemote(selectedSkill.sourceUrl!)}>
                在线查看
              </button>
            )}
            {selectedSkill.homepageUrl && selectedSkill.homepageUrl !== selectedSkill.sourceUrl && (
              <button
                type="button"
                className="dialog-btn secondary"
                onClick={() => openRemote(selectedSkill.homepageUrl!)}
              >
                项目主页
              </button>
            )}
          </div>
        </section>

        {FEATURED_SKILL_DETAILS[selectedSkill.slug] ? (
          <div className="skills-detail-grid">
            <section className="skills-detail-panel">
              <h4>怎么建模</h4>
              <ol className="skills-detail-list">
                {selectedSkillDetail.modelingPath.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            </section>
            <section className="skills-detail-panel">
              <h4>出了问题先看</h4>
              <ol className="skills-detail-list">
                {selectedSkillDetail.debuggingPath.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            </section>
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <div className="skills-system">
      <div className="library-page-header">
        <div>
          <h2 className="library-page-title">{pageTitle}</h2>
          <p className="library-page-desc">{pageDesc}</p>
        </div>
        <div className="library-page-actions">
          {page !== "overview" && (
            <button type="button" className="dialog-btn secondary" onClick={goOverview}>
              返回技能广场
            </button>
          )}
          <button type="button" className="dialog-btn secondary" onClick={() => void handleRefresh()} disabled={loading}>
            {loading ? "刷新中..." : "刷新目录"}
          </button>
        </div>
      </div>

      {notice && <div className={`skills-banner skills-banner--${notice.tone}`}>{notice.text}</div>}

      {page === "overview" && renderOverview()}
      {page === "create" && renderCreatePage()}
      {page === "import" && renderImportPage()}
      {page === "detail" && renderDetailPage()}
    </div>
  );
}
