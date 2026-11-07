import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useEffect,
  useMemo,
  type ReactNode,
  type Dispatch,
} from "react";
import type {
  AgentMode,
  AppView,
  SettingsSection,
  AssistantPresentation,
  ChatMessage,
  MessageRole,
  RunEvent,
  DialogType,
  Conversation,
  ConversationGroup,
  ClarifyingQuestion,
} from "../lib/types";
import {
  loadConversations,
  saveConversations,
  loadConversationGroups,
  saveConversationGroups,
  loadMessagesByConversation,
  saveMessagesByConversation,
  loadCurrentConversationId,
  saveCurrentConversationId,
} from "../lib/conversationStorage";
import {
  loadApiConfig,
  isProviderId,
  type LLMBackendId,
} from "../lib/apiConfig";
import { parseStructuredAssistantText } from "../lib/structuredAssistantMessage";

function genId(): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return `conv_${crypto.randomUUID()}`;
    }
  } catch {
    // ignore
  }
  return `conv_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
}

let messageCounter = 0;
function nextMsgId(): string {
  return `msg_${++messageCounter}_${Date.now()}`;
}

interface AppState {
  conversations: Conversation[];
  conversationGroups: ConversationGroup[];
  currentConversationId: string | null;
  messagesByConversation: Record<string, ChatMessage[]>;
  /** 当前工作空间根目录（由当前会话派生） */
  workspaceDir: string | null;
  view: AppView;
  settingsTab: SettingsSection;
  mode: AgentMode;
  backend: LLMBackendId | null;
  outputDefault: string | null;
  execCodeOnly: boolean;
  /** 正在执行 run/stream 的会话 id，null 表示无执行中 */
  busyConversationId: string | null;
  /** 编辑并重新建模时预填输入框的内容，设置后 Prompt 会同步到输入框 */
  editingDraft: string | null;
  /** 重新编辑某条用户消息时，下次发送会从该下标截断后续消息 */
  editResumeFromIndex: number | null;
  activeDialog: DialogType;
  /** 计划模式下，等待用户澄清的问题列表 */
  pendingPlanQuestions: ClarifyingQuestion[] | null;
  /** 上一次用于生成 Plan 的原始输入，用于在澄清问题后复用 */
  lastPlanInput: string | null;
  /** 探讨阶段讨论卡已 finalized，可提示用户进入规划 */
  discussionReadyForPlan: boolean;
  /** 计算后端：CPU / GPU / GPU 待命 */
  computeBackend: {
    mode: "cpu" | "gpu" | "gpu_standby";
    label: string;
    detail: string;
    gpuAvailable: boolean;
    gpuName: string;
  };
  /** 求解实时进度（对话框底部展示） */
  solveProgress: {
    active: boolean;
    percent: number;
    message: string;
    phase: string;
  };
}

type AppAction =
  | { type: "NEW_CONVERSATION"; workspaceDir: string; title?: string }
  /** 在已有工作空间下新建另一个 Agent 任务（共享目录，隔离 context/tasks） */
  | { type: "NEW_AGENT_TASK"; workspaceDir?: string; title?: string }
  | { type: "SWITCH_CONVERSATION"; id: string }
  | { type: "SET_CONVERSATION_TITLE"; id: string; title: string }
  | { type: "SET_CONVERSATION_WORKSPACE_DIR"; id: string; path: string }
  | { type: "DELETE_CONVERSATION"; id: string }
  | { type: "ADD_CONVERSATION_GROUP"; name: string }
  | { type: "RENAME_CONVERSATION_GROUP"; id: string; name: string }
  | { type: "DELETE_CONVERSATION_GROUP"; id: string }
  | { type: "MOVE_CONVERSATION_TO_GROUP"; conversationId: string; groupId: string | null }
  | {
      type: "ADD_MESSAGE";
      conversationId: string;
      role: MessageRole;
      text: string;
      success?: boolean;
      events?: RunEvent[];
      caseData?: ChatMessage["caseData"];
      caseSavedPath?: string | null;
      assistantPresentation?: AssistantPresentation;
    }
  | { type: "APPEND_EVENT"; conversationId: string; event: RunEvent }
  | {
      type: "FINALIZE_LAST";
      conversationId: string;
      text: string;
      success: boolean;
    }
  | { type: "SET_MODE"; mode: AgentMode }
  | { type: "SET_VIEW"; view: AppView; settingsTab?: SettingsSection }
  | { type: "SET_BACKEND"; backend: LLMBackendId | null }
  | { type: "SET_OUTPUT"; output: string | null }
  | { type: "SET_EXEC_CODE_ONLY"; value: boolean }
  | { type: "SET_BUSY_CONVERSATION"; conversationId: string | null }
  | {
      type: "SET_EDITING_DRAFT";
      text: string | null;
      resumeFromIndex?: number | null;
    }
  | { type: "CLEAR_EDIT_RESUME" }
  | { type: "REMOVE_MESSAGES_FROM_INDEX"; conversationId: string; fromIndex: number }
  | { type: "SET_DIALOG"; dialog: DialogType }
  | { type: "SET_PLAN_QUESTIONS"; questions: ClarifyingQuestion[] | null }
  | { type: "CLEAR_PLAN_QUESTIONS" }
  | { type: "SET_LAST_PLAN_INPUT"; input: string | null }
  | { type: "SET_DISCUSSION_READY_FOR_PLAN"; value: boolean }
  | {
      type: "SET_COMPUTE_BACKEND";
      mode?: "cpu" | "gpu" | "gpu_standby";
      label?: string;
      detail?: string;
      gpuAvailable?: boolean;
      gpuName?: string;
    }
  | {
      type: "SET_SOLVE_PROGRESS";
      active?: boolean;
      percent?: number;
      message?: string;
      phase?: string;
    }
  | { type: "HYDRATE"; state: Partial<AppState> };

const DEFAULT_COMPUTE_BACKEND: AppState["computeBackend"] = {
  mode: "cpu",
  label: "CPU 计算",
  detail: "默认使用 CPU 多核求解；COMSOL GPU 仅覆盖部分场景。",
  gpuAvailable: false,
  gpuName: "",
};

const DEFAULT_SOLVE_PROGRESS: AppState["solveProgress"] = {
  active: false,
  percent: 0,
  message: "",
  phase: "",
};

function workspaceDirOf(
  conversations: Conversation[],
  currentId: string | null
): string | null {
  if (!currentId) return null;
  const conv = conversations.find((c) => c.id === currentId);
  const path = conv?.workspaceDir?.trim();
  return path || null;
}

const SETTINGS_TABS: SettingsSection[] = [
  "theme",
  "llm",
  "comsol",
  "models",
  "case-library",
];

function normalizeSettingsTab(tab: unknown): SettingsSection {
  if (typeof tab === "string" && (SETTINGS_TABS as string[]).includes(tab)) {
    return tab as SettingsSection;
  }
  return "theme";
}

function getInitialState(): AppState {
  const conversations = loadConversations();
  const conversationGroups = loadConversationGroups();
  const messagesByConversation = loadMessagesByConversation() as Record<
    string,
    ChatMessage[]
  >;
  const currentId = loadCurrentConversationId();
  const apiCfg = loadApiConfig();
  const preferred = apiCfg.preferred_backend;
  const backend = preferred && isProviderId(preferred) ? preferred : null;

  if (conversations.length === 0) {
    return {
      conversations: [],
      conversationGroups,
      currentConversationId: null,
      messagesByConversation: {},
      workspaceDir: null,
      view: "session",
      settingsTab: "theme",
      mode: "run",
      backend,
      outputDefault: null,
      execCodeOnly: false,
      busyConversationId: null,
      editingDraft: null,
      editResumeFromIndex: null,
      activeDialog: null,
      pendingPlanQuestions: null,
      lastPlanInput: null,
      discussionReadyForPlan: false,
      computeBackend: { ...DEFAULT_COMPUTE_BACKEND },
      solveProgress: { ...DEFAULT_SOLVE_PROGRESS },
    };
  }

  const id = currentId && conversations.some((c: Conversation) => c.id === currentId)
    ? currentId
    : conversations[0].id;
  return {
    conversations,
    conversationGroups,
    currentConversationId: id,
    messagesByConversation,
    workspaceDir: workspaceDirOf(conversations, id),
    view: "session",
    settingsTab: "theme",
    mode: "run",
    backend,
    outputDefault: null,
    execCodeOnly: false,
    busyConversationId: null,
    editingDraft: null,
    editResumeFromIndex: null,
    activeDialog: null,
    pendingPlanQuestions: null,
    lastPlanInput: null,
    discussionReadyForPlan: false,
    computeBackend: { ...DEFAULT_COMPUTE_BACKEND },
    solveProgress: { ...DEFAULT_SOLVE_PROGRESS },
  };
}

const initialState = getInitialState();

function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "NEW_CONVERSATION": {
      const workspaceDir = action.workspaceDir.trim();
      if (!workspaceDir) return state;
      const title = action.title?.trim() || "Agent 任务 1";
      const conv: Conversation = {
        id: genId(),
        title,
        createdAt: Date.now(),
        workspaceDir,
        groupId: null,
      };
      return {
        ...state,
        conversations: [conv, ...state.conversations],
        currentConversationId: conv.id,
        workspaceDir,
        messagesByConversation: {
          ...state.messagesByConversation,
          [conv.id]: [],
        },
        discussionReadyForPlan: false,
        view: "session",
      };
    }
    case "NEW_AGENT_TASK": {
      const workspaceDir = (
        action.workspaceDir?.trim() ||
        state.workspaceDir ||
        ""
      ).trim();
      if (!workspaceDir) return state;
      const siblings = state.conversations.filter(
        (c) => (c.workspaceDir || "").trim() === workspaceDir
      );
      const title =
        action.title?.trim() || `Agent 任务 ${siblings.length + 1}`;
      const conv: Conversation = {
        id: genId(),
        title,
        createdAt: Date.now(),
        workspaceDir,
        groupId: null,
      };
      return {
        ...state,
        conversations: [conv, ...state.conversations],
        currentConversationId: conv.id,
        workspaceDir,
        messagesByConversation: {
          ...state.messagesByConversation,
          [conv.id]: [],
        },
        discussionReadyForPlan: false,
        view: "session",
      };
    }
    case "ADD_CONVERSATION_GROUP": {
      const name = action.name.trim();
      if (!name) return state;
      const group: ConversationGroup = {
        id: `grp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        name,
        createdAt: Date.now(),
      };
      return { ...state, conversationGroups: [...state.conversationGroups, group] };
    }
    case "RENAME_CONVERSATION_GROUP": {
      const name = action.name.trim();
      if (!name) return state;
      return {
        ...state,
        conversationGroups: state.conversationGroups.map((g) =>
          g.id === action.id ? { ...g, name } : g
        ),
      };
    }
    case "DELETE_CONVERSATION_GROUP": {
      return {
        ...state,
        conversationGroups: state.conversationGroups.filter((g) => g.id !== action.id),
        conversations: state.conversations.map((c) =>
          c.groupId === action.id ? { ...c, groupId: null } : c
        ),
      };
    }
    case "MOVE_CONVERSATION_TO_GROUP":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.conversationId ? { ...c, groupId: action.groupId } : c
        ),
      };
    case "SWITCH_CONVERSATION":
      return {
        ...state,
        currentConversationId: action.id,
        workspaceDir: workspaceDirOf(state.conversations, action.id),
        discussionReadyForPlan: false,
        view: "session",
      };
    case "SET_CONVERSATION_TITLE": {
      const list = state.conversations.map((c) =>
        c.id === action.id ? { ...c, title: action.title } : c
      );
      return { ...state, conversations: list };
    }
    case "SET_CONVERSATION_WORKSPACE_DIR": {
      const path = action.path.trim();
      if (!path) return state;
      const list = state.conversations.map((c) =>
        c.id === action.id ? { ...c, workspaceDir: path } : c
      );
      return {
        ...state,
        conversations: list,
        workspaceDir:
          state.currentConversationId === action.id
            ? path
            : state.workspaceDir,
      };
    }
    case "DELETE_CONVERSATION": {
      const list = state.conversations.filter((c) => c.id !== action.id);
      const nextMessages = { ...state.messagesByConversation };
      delete nextMessages[action.id];
      const nextId =
        state.currentConversationId === action.id
          ? list.length > 0
            ? list[0].id
            : null
          : state.currentConversationId;
      return {
        ...state,
        conversations: list,
        messagesByConversation: nextMessages,
        currentConversationId: nextId,
        workspaceDir: workspaceDirOf(list, nextId),
      };
    }
    case "ADD_MESSAGE": {
      const { conversationId, role, text, success, events } = action;
      const msg: ChatMessage = {
        id: nextMsgId(),
        role,
        text,
        time: Date.now(),
        success,
        events,
        caseData: action.caseData ?? null,
        caseSavedPath: action.caseSavedPath ?? null,
        assistantPresentation: action.assistantPresentation,
      };
      const prev = state.messagesByConversation[conversationId] ?? [];
      return {
        ...state,
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: [...prev, msg],
        },
      };
    }
    case "APPEND_EVENT": {
      const { conversationId, event } = action;
      const prev = state.messagesByConversation[conversationId] ?? [];
      const last = prev[prev.length - 1];
      if (!last || last.role !== "assistant") return state;
      const updated = [
        ...prev.slice(0, -1),
        { ...last, events: [...(last.events ?? []), event] },
      ];
      return {
        ...state,
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: updated,
        },
      };
    }
    case "FINALIZE_LAST": {
      const { conversationId, text, success } = action;
      const prev = state.messagesByConversation[conversationId] ?? [];
      const last = prev[prev.length - 1];
      if (!last || last.role !== "assistant") return state;
      // 从 run_end / step_end / exec_result 取最终模型路径，保证成功时展示位置与打开入口
      let modelPath: string | null | undefined = last.modelPath;
      const events = last.events ?? [];
      for (let i = events.length - 1; i >= 0; i--) {
        const e = events[i];
        const d = e?.data;
        const path =
          (typeof d?.model_path === "string" && d.model_path) ||
          (typeof d?.saved_path === "string" && d.saved_path) ||
          (typeof (d?.result as { model_path?: unknown } | undefined)?.model_path ===
            "string" &&
            (d?.result as { model_path?: string }).model_path) ||
          (typeof (d?.result as { saved_path?: unknown } | undefined)?.saved_path ===
            "string" &&
            (d?.result as { saved_path?: string }).saved_path) ||
          null;
        if (path) {
          modelPath = path;
          break;
        }
      }
      const structured = parseStructuredAssistantText(text);
      let displayText = text;
      if (structured) {
        displayText = structured.text;
        if (!modelPath && structured.modelPath) {
          modelPath = structured.modelPath;
        }
      }
      const updated = [
        ...prev.slice(0, -1),
        {
          ...last,
          text: displayText,
          success,
          modelPath: modelPath ?? last.modelPath,
        },
      ];
      return {
        ...state,
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: updated,
        },
      };
    }
    case "SET_MODE":
      return {
        ...state,
        mode: action.mode,
        discussionReadyForPlan:
          action.mode === "discuss" ? state.discussionReadyForPlan : false,
      };
    case "SET_VIEW": {
      if (action.view === "session") return { ...state, view: "session" };
      const openedFromView: Partial<Record<AppView, SettingsSection>> = {
        "case-library": "case-library",
      };
      const settingsTab =
        action.settingsTab ?? openedFromView[action.view] ?? state.settingsTab;
      return {
        ...state,
        view: "settings",
        settingsTab: normalizeSettingsTab(settingsTab),
      };
    }
    case "SET_DISCUSSION_READY_FOR_PLAN":
      return { ...state, discussionReadyForPlan: action.value };
    case "SET_BACKEND":
      return { ...state, backend: action.backend };
    case "SET_OUTPUT":
      return { ...state, outputDefault: action.output };
    case "SET_EXEC_CODE_ONLY":
      return { ...state, execCodeOnly: action.value };
    case "SET_BUSY_CONVERSATION":
      return {
        ...state,
        busyConversationId: action.conversationId,
        ...(action.conversationId == null
          ? { solveProgress: { ...DEFAULT_SOLVE_PROGRESS } }
          : {}),
      };
    case "SET_COMPUTE_BACKEND":
      return {
        ...state,
        computeBackend: {
          mode: action.mode ?? state.computeBackend.mode,
          label: action.label ?? state.computeBackend.label,
          detail: action.detail ?? state.computeBackend.detail,
          gpuAvailable:
            action.gpuAvailable ?? state.computeBackend.gpuAvailable,
          gpuName: action.gpuName ?? state.computeBackend.gpuName,
        },
      };
    case "SET_SOLVE_PROGRESS":
      return {
        ...state,
        solveProgress: {
          active: action.active ?? state.solveProgress.active,
          percent:
            typeof action.percent === "number"
              ? Math.max(0, Math.min(100, action.percent))
              : state.solveProgress.percent,
          message: action.message ?? state.solveProgress.message,
          phase: action.phase ?? state.solveProgress.phase,
        },
      };
    case "SET_EDITING_DRAFT":
      return {
        ...state,
        editingDraft: action.text,
        editResumeFromIndex:
          action.text == null ? null : (action.resumeFromIndex ?? null),
      };
    case "CLEAR_EDIT_RESUME":
      return { ...state, editResumeFromIndex: null };
    case "REMOVE_MESSAGES_FROM_INDEX": {
      const { conversationId, fromIndex } = action;
      const prev = state.messagesByConversation[conversationId] ?? [];
      const next = prev.slice(0, fromIndex);
      return {
        ...state,
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: next,
        },
      };
    }
    case "SET_DIALOG":
      return { ...state, activeDialog: action.dialog };
    case "SET_PLAN_QUESTIONS":
      return { ...state, pendingPlanQuestions: action.questions };
    case "CLEAR_PLAN_QUESTIONS":
      return { ...state, pendingPlanQuestions: null };
    case "SET_LAST_PLAN_INPUT":
      return { ...state, lastPlanInput: action.input };
    case "HYDRATE": {
      const next = { ...state, ...action.state };
      const openedFromView: Partial<Record<AppView, SettingsSection>> = {
        "case-library": "case-library",
      };
      const mapped = openedFromView[next.view];
      if (mapped) {
        next.view = "settings";
        next.settingsTab = mapped;
      }
      next.settingsTab = normalizeSettingsTab(next.settingsTab);
      next.computeBackend = {
        ...DEFAULT_COMPUTE_BACKEND,
        ...(next.computeBackend ?? {}),
      };
      next.solveProgress = {
        ...DEFAULT_SOLVE_PROGRESS,
        ...(next.solveProgress ?? {}),
      };
      return next;
    }
    default:
      return state;
  }
}

interface AppStateContextValue {
  state: AppState;
  dispatch: Dispatch<AppAction>;
  /** 当前会话的消息列表 */
  messages: ChatMessage[];
  /** 当前会话标题 */
  sessionTitle: string;
  addMessage: (
    role: MessageRole,
    text: string,
    opts?: {
      success?: boolean;
      events?: RunEvent[];
      caseData?: ChatMessage["caseData"];
      caseSavedPath?: string | null;
      assistantPresentation?: AssistantPresentation;
    }
  ) => void;
}

const AppStateContext = createContext<AppStateContextValue | undefined>(
  undefined
);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState);

  const messages = useMemo(
    () =>
      state.currentConversationId
        ? state.messagesByConversation[state.currentConversationId] ?? []
        : [],
    [state.currentConversationId, state.messagesByConversation]
  );

  const sessionTitle = useMemo(
    () =>
      state.currentConversationId
        ? state.conversations.find((c) => c.id === state.currentConversationId)
            ?.title ?? "新会话"
        : "新会话",
    [state.currentConversationId, state.conversations]
  );

  const addMessage = useCallback(
    (
      role: MessageRole,
      text: string,
      opts?: {
        success?: boolean;
        events?: RunEvent[];
        caseData?: ChatMessage["caseData"];
        caseSavedPath?: string | null;
        assistantPresentation?: AssistantPresentation;
      }
    ) => {
      const id = state.currentConversationId;
      if (!id) return;
      dispatch({
        type: "ADD_MESSAGE",
        conversationId: id,
        role,
        text,
        success: opts?.success,
        events: opts?.events,
        caseData: opts?.caseData,
        caseSavedPath: opts?.caseSavedPath ?? null,
        assistantPresentation: opts?.assistantPresentation,
      });
    },
    [state.currentConversationId, dispatch]
  );

  useEffect(() => {
    saveConversations(state.conversations);
  }, [state.conversations]);

  useEffect(() => {
    saveConversationGroups(state.conversationGroups);
  }, [state.conversationGroups]);

  useEffect(() => {
    saveMessagesByConversation(
      state.messagesByConversation as unknown as Record<string, unknown[]>
    );
  }, [state.messagesByConversation]);

  useEffect(() => {
    if (state.currentConversationId) {
      saveCurrentConversationId(state.currentConversationId);
    }
  }, [state.currentConversationId]);

  const value: AppStateContextValue = {
    state,
    dispatch,
    messages,
    sessionTitle,
    addMessage,
  };

  return (
    <AppStateContext.Provider value={value}>
      {children}
    </AppStateContext.Provider>
  );
}

export function useAppState() {
  const ctx = useContext(AppStateContext);
  if (!ctx)
    throw new Error("useAppState must be used within AppStateProvider");
  return ctx;
}
