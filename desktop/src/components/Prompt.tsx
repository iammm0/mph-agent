import {
  useState,
  useRef,
  useCallback,
  useEffect,
  useMemo,
  type KeyboardEvent,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useAppState } from "../context/AppStateContext";
import { useBridge } from "../hooks/useBridge";
import {
  API_CONFIG_UPDATED_EVENT,
  loadApiConfig,
} from "../lib/apiConfig";
import {
  PROMPT_PLUS_MENU_COMMANDS,
  PROMPT_MODE_ITEMS,
} from "../lib/types";
import {
  estimateContextUsage,
  formatCompactTokenCount,
} from "../lib/contextUsage";
import type { PromptExtensionItem, AgentMode } from "../lib/types";
import { Icon } from "./Icon";

export function Prompt() {
  const { state, dispatch } = useAppState();
  const { handleSubmit, abortRun, triggerExtensionAction } = useBridge();
  const [value, setValue] = useState("");
  const [modeToast, setModeToast] = useState("");
  const [showPlusMenu, setShowPlusMenu] = useState(false);
  const [apiConfig, setApiConfig] = useState(() => loadApiConfig());
  const [promptContextText, setPromptContextText] = useState("");
  const [pendingTurnInput, setPendingTurnInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const plusWrapRef = useRef<HTMLDivElement>(null);
  const contextRequestRef = useRef(0);

  useEffect(() => {
    if (state.editingDraft != null) {
      setValue(state.editingDraft);
      dispatch({ type: "SET_EDITING_DRAFT", text: null });
    }
  }, [state.editingDraft, dispatch]);

  useEffect(() => {
    if (!showPlusMenu) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const el = plusWrapRef.current;
      if (el && !el.contains(e.target as Node)) {
        setShowPlusMenu(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [showPlusMenu]);

  useEffect(() => {
    if (!modeToast) return;
    const timer = window.setTimeout(() => setModeToast(""), 1800);
    return () => window.clearTimeout(timer);
  }, [modeToast]);

  const refreshApiConfig = useCallback(() => {
    setApiConfig(loadApiConfig());
  }, []);

  useEffect(() => {
    const handleApiConfigUpdated = () => refreshApiConfig();
    const handleStorage = (event: StorageEvent) => {
      if (
        event.key === "mph-agent-api-config" ||
        event.key === "comsol-agent-api-config"
      ) {
        refreshApiConfig();
      }
    };

    window.addEventListener(API_CONFIG_UPDATED_EVENT, handleApiConfigUpdated);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener(
        API_CONFIG_UPDATED_EVENT,
        handleApiConfigUpdated
      );
      window.removeEventListener("storage", handleStorage);
    };
  }, [refreshApiConfig]);

  const refreshPromptContext = useCallback(async (conversationId: string | null) => {
    const requestId = ++contextRequestRef.current;
    if (!conversationId) {
      setPromptContextText("");
      return;
    }

    try {
      const res = await invoke<{ ok: boolean; message: string }>("bridge_send", {
        cmd: "context_prompt_context",
        payload: { conversation_id: conversationId },
      });
      if (contextRequestRef.current !== requestId) return;
      setPromptContextText(res.ok ? res.message : "");
    } catch {
      if (contextRequestRef.current === requestId) {
        setPromptContextText("");
      }
    }
  }, []);

  useEffect(() => {
    if (state.busyConversationId != null) return;
    void refreshPromptContext(state.currentConversationId);
    const timer = window.setTimeout(() => {
      void refreshPromptContext(state.currentConversationId);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [
    state.currentConversationId,
    state.busyConversationId,
    refreshPromptContext,
  ]);

  useEffect(() => {
    if (state.busyConversationId == null) {
      setPendingTurnInput("");
    }
  }, [state.busyConversationId]);

  const submit = useCallback(() => {
    const text = value.trim();
    if (!text || state.busyConversationId != null) return;
    setPendingTurnInput(text);
    handleSubmit(text);
    setValue("");
  }, [value, state.busyConversationId, handleSubmit]);

  const applyMode = useCallback(
    (mode: AgentMode) => {
      if (state.mode === mode) return;
      dispatch({ type: "SET_MODE", mode });
      if (mode === "run") {
        setModeToast("已切换为执行模式（Run）");
      } else if (mode === "discuss") {
        setModeToast("已切换为探讨模式（Discuss），可与 LLM 闲聊");
      } else {
        setModeToast("已切换为规划模式（Plan）");
      }
    },
    [state.mode, dispatch]
  );

  const onPlusSelect = useCallback(
    async (cmd: PromptExtensionItem) => {
      setShowPlusMenu(false);
      if (cmd.name === "case") {
        const selected = await open({
          multiple: false,
          title: "选择要读取的 COMSOL 模型文件",
          filters: [{ name: "COMSOL Model", extensions: ["mph"] }],
        });
        if (typeof selected === "string") {
          await triggerExtensionAction("case", { modelPath: selected });
        }
        return;
      }
      await triggerExtensionAction(cmd.name);
    },
    [triggerExtensionAction]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Escape") {
        if (showPlusMenu) {
          e.preventDefault();
          setShowPlusMenu(false);
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submit();
      }
    },
    [submit, showPlusMenu]
  );

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, []);

  const busy = state.busyConversationId != null;
  const activeInputText = busy ? pendingTurnInput : value;
  const contextUsage = useMemo(
    () =>
      estimateContextUsage({
        config: apiConfig,
        backend: state.backend,
        mode: state.mode,
        memoryContextText: promptContextText,
        draftText: activeInputText,
      }),
    [
      apiConfig,
      state.backend,
      state.mode,
      promptContextText,
      activeInputText,
    ]
  );
  const contextFillPercent =
    contextUsage.usedTokens > 0
      ? Math.max(2, contextUsage.percent)
      : contextUsage.percent;
  const contextMeterTitle = [
    `上下文窗口估算：${contextUsage.windowSourceLabel}`,
    `当前模型：${contextUsage.providerLabel} · ${contextUsage.modelLabel}`,
    `已用：${formatCompactTokenCount(contextUsage.usedTokens)} / ${formatCompactTokenCount(
      contextUsage.maxTokens
    )} tokens`,
    `输入：${formatCompactTokenCount(contextUsage.inputTokens)}`,
    `记忆：${formatCompactTokenCount(contextUsage.memoryTokens)}`,
    `系统：${formatCompactTokenCount(contextUsage.overheadTokens)}`,
    `安全剩余：${formatCompactTokenCount(contextUsage.safeRemainingTokens)}`,
  ].join("\n");

  return (
    <div className="prompt-area">
      {state.discussionReadyForPlan && state.mode === "discuss" && (
        <div className="prompt-plan-nudge" role="status">
          <span className="prompt-plan-nudge__text">
            探讨结论已就绪，可进入规划模式编写建模需求；也可点下方「规划」或 + 菜单中的扩展功能。
          </span>
          <button
            type="button"
            className="prompt-plan-nudge__btn"
            onClick={() => dispatch({ type: "SET_MODE", mode: "plan" })}
          >
            进入规划
          </button>
        </div>
      )}
      <div className="prompt-toolbar">
        {modeToast && <div className="prompt-mode-toast">{modeToast}</div>}
        <div
          className="prompt-mode-segment"
          role="group"
          aria-label="工作模式"
        >
          {PROMPT_MODE_ITEMS.map((item) => (
            <button
              key={item.mode}
              type="button"
              className={`prompt-mode-btn ${item.mode} ${state.mode === item.mode ? "active" : ""}`}
              title={item.title}
              onClick={() => applyMode(item.mode)}
              disabled={busy}
            >
              <Icon name={item.icon} size={13} />
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <div
        className={`prompt-wrapper${busy ? " prompt-wrapper--busy" : ""}`}
        style={{ position: "relative" }}
      >
        <div className="prompt-plus-wrap" ref={plusWrapRef}>
          <button
            type="button"
            className="prompt-plus-btn"
            disabled={busy}
            aria-expanded={showPlusMenu}
            aria-haspopup="menu"
            title="扩展功能"
            onClick={() => setShowPlusMenu((v) => !v)}
          >
            <Icon name={showPlusMenu ? "minus" : "add"} size={16} />
          </button>
          {showPlusMenu && (
            <div className="prompt-plus-menu" role="menu">
              {PROMPT_PLUS_MENU_COMMANDS.map((cmd) => (
                <button
                  key={cmd.name}
                  type="button"
                  role="menuitem"
                  className="prompt-plus-menu-item"
                  onClick={() => void onPlusSelect(cmd)}
                >
                  <span className="prompt-plus-menu-row">
                    <Icon name={cmd.icon} size={15} />
                    <span className="prompt-plus-menu-cmd">{cmd.label}</span>
                  </span>
                  <span className="prompt-plus-menu-desc">{cmd.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <textarea
          ref={textareaRef}
          className="prompt-input"
          rows={1}
          placeholder="输入建模需求…（扩展功能请点击 +）"
          value={value}
          disabled={busy}
          onChange={(e) => {
            setValue(e.target.value);
            autoResize();
          }}
          onKeyDown={handleKeyDown}
        />
        <button
          className="prompt-send"
          disabled={busy || !value.trim()}
          onClick={submit}
          title="发送 (Enter)"
        >
          <Icon name="send-2" size={16} />
        </button>
        {busy && (
          <button
            type="button"
            className="prompt-stop"
            onClick={abortRun}
            title="停止建模"
          >
            <Icon name="stop" size={14} />
            停止
          </button>
        )}
      </div>
      <div
        className={`prompt-context-meter ${contextUsage.status}`}
        title={contextMeterTitle}
      >
        <span
          className="prompt-context-meter__icon"
          aria-hidden="true"
          style={{
            backgroundImage: `conic-gradient(var(--context-meter-color) ${Math.round(
              contextUsage.ratio * 360
            )}deg, color-mix(in srgb, var(--context-meter-color) 18%, transparent) 0deg)`,
          }}
        >
          <span className="prompt-context-meter__icon-core" />
        </span>
        <div className="prompt-context-meter__copy">
          <span className="prompt-context-meter__title">
            上下文 {contextUsage.percent}% 已用
          </span>
          <span className="prompt-context-meter__model">
            {contextUsage.providerLabel} · {contextUsage.modelLabel}
          </span>
        </div>
        <div className="prompt-context-meter__bar" aria-hidden="true">
          <span
            className="prompt-context-meter__bar-fill"
            style={{ width: `${contextFillPercent}%` }}
          />
        </div>
        <div className="prompt-context-meter__numbers">
          <span>
            {formatCompactTokenCount(contextUsage.usedTokens)} /{" "}
            {formatCompactTokenCount(contextUsage.maxTokens)}
          </span>
          <span>
            余量 {formatCompactTokenCount(contextUsage.safeRemainingTokens)}
          </span>
        </div>
      </div>
    </div>
  );
}
