import {
  useState,
  useRef,
  useCallback,
  useEffect,
  useMemo,
  type KeyboardEvent,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import { useAppState } from "../context/AppStateContext";
import { useBridge } from "../hooks/useBridge";
import {
  API_CONFIG_UPDATED_EVENT,
  apiConfigToEnv,
  COMPUTE_PREFERENCE_OPTIONS,
  getProviderConfig,
  loadApiConfig,
  nextComputePreference,
  normalizeComputePreference,
  saveApiConfig,
} from "../lib/apiConfig";
import { ModelPicker } from "./ModelPicker";
import { Icon } from "./Icon";

function formatTokenCount(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  return Math.round(n).toLocaleString("zh-CN");
}

function folderName(path: string | null | undefined): string {
  if (!path?.trim()) return "未选择工作空间";
  const parts = path.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export function Prompt() {
  const { state, dispatch, messages } = useAppState();
  const { handleSubmit, abortRun } = useBridge();
  const [value, setValue] = useState("");
  const [apiConfig, setApiConfig] = useState(() => loadApiConfig());
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const workspaceWrapRef = useRef<HTMLDivElement>(null);

  const computePref = normalizeComputePreference(apiConfig.compute_preference);
  const computePrefMeta =
    COMPUTE_PREFERENCE_OPTIONS.find((o) => o.id === computePref) ??
    COMPUTE_PREFERENCE_OPTIONS[0];
  const busy = state.busyConversationId != null;

  const cycleComputePreference = useCallback(async () => {
    if (busy) return;
    const next = nextComputePreference(computePref);
    const nextConfig = { ...apiConfig, compute_preference: next };
    setApiConfig(nextConfig);
    saveApiConfig(nextConfig);
    const meta =
      COMPUTE_PREFERENCE_OPTIONS.find((o) => o.id === next) ??
      COMPUTE_PREFERENCE_OPTIONS[0];
    dispatch({
      type: "SET_COMPUTE_BACKEND",
      mode: next === "cpu" ? "cpu" : state.computeBackend.gpuAvailable ? "gpu_standby" : "cpu",
      label:
        next === "cpu"
          ? "仅 CPU（用户指定）"
          : next === "gpu"
            ? "优先 GPU（有卡则尝试）"
            : state.computeBackend.gpuAvailable
              ? "GPU 待命 · CPU 计算"
              : "CPU 计算",
      detail: meta.hint,
    });
    try {
      await invoke("bridge_send", {
        cmd: "config_save",
        payload: {
          config: {
            COMSOL_COMPUTE_PREFERENCE: next,
          },
          conversation_id: state.currentConversationId,
          workspace_dir: state.workspaceDir ?? undefined,
        },
      });
    } catch {
      // 本地已保存；bridge 未就绪时下次启动仍可读 .env / localStorage
    }
  }, [
    apiConfig,
    busy,
    computePref,
    dispatch,
    state.computeBackend.gpuAvailable,
    state.currentConversationId,
    state.workspaceDir,
  ]);

  const tokenStats = useMemo(() => {
    let prompt = 0;
    let completion = 0;
    let total = 0;
    let calls = 0;
    for (const msg of messages) {
      for (const evt of msg.events ?? []) {
        if (evt.type !== "token_usage") continue;
        const d = evt.data ?? {};
        prompt += Number(d.prompt_tokens) || 0;
        completion += Number(d.completion_tokens) || 0;
        total += Number(d.total_tokens) || 0;
        calls += 1;
      }
    }
    return { prompt, completion, total, calls };
  }, [messages]);

  useEffect(() => {
    if (state.editingDraft != null) {
      setValue(state.editingDraft);
      dispatch({ type: "SET_EDITING_DRAFT", text: null });
    }
  }, [state.editingDraft, dispatch]);

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

  useEffect(() => {
    if (!workspaceOpen) return;
    const onDocMouseDown = (event: MouseEvent) => {
      const el = workspaceWrapRef.current;
      if (el && !el.contains(event.target as Node)) {
        setWorkspaceOpen(false);
      }
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setWorkspaceOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [workspaceOpen]);

  const submit = useCallback(() => {
    const text = value.trim();
    if (!text || state.busyConversationId != null) return;
    handleSubmit(text);
    setValue("");
  }, [value, state.busyConversationId, handleSubmit]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submit();
      }
    },
    [submit]
  );

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, []);

  const deepseek = getProviderConfig(apiConfig, "deepseek");
  const currentConv = state.conversations.find(
    (c) => c.id === state.currentConversationId
  );
  const workspaceFolder = folderName(state.workspaceDir) || "未选择工作空间";
  const taskTitle = currentConv?.title?.trim() || "Agent 任务";
  const workspaceLabel = state.workspaceDir
    ? `${workspaceFolder} · ${taskTitle}`
    : "未选择工作空间";

  const selectModel = useCallback((model: string) => {
    const next = loadApiConfig();
    const provider = getProviderConfig(next, "deepseek");
    next.providers.deepseek = { ...provider, model };
    next.preferred_backend = "deepseek";
    saveApiConfig(next);
    setApiConfig(loadApiConfig());
    void invoke("bridge_send", {
      cmd: "config_save",
      payload: { config: apiConfigToEnv(loadApiConfig()) },
    }).catch(() => {});
  }, []);

  const switchWorkspace = useCallback(
    (id: string) => {
      dispatch({ type: "SWITCH_CONVERSATION", id });
      dispatch({ type: "SET_VIEW", view: "session" });
      setWorkspaceOpen(false);
    },
    [dispatch]
  );

  return (
    <div className="prompt-area">
      <div
        className={`prompt-wrapper${busy ? " prompt-wrapper--busy" : ""}`}
      >
        <div className="prompt-main-row">
          <div className="prompt-input-wrap">
            <textarea
              ref={textareaRef}
              className="prompt-input"
              rows={1}
              placeholder="描述建模需求，或提出一个问题…"
              value={value}
              disabled={busy}
              onChange={(e) => {
                setValue(e.target.value);
                autoResize();
              }}
              onKeyDown={handleKeyDown}
            />
          </div>
          <div className="prompt-toolbar-actions">
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
            <button
              className="prompt-send"
              disabled={busy || !value.trim()}
              onClick={submit}
              title="发送 (Enter)"
            >
              <Icon name="send" type="bold" size={16} color="#fff" />
            </button>
          </div>
        </div>
      </div>

      <div className="composer-status">
        <div className="composer-status__left" ref={workspaceWrapRef}>
          <button
            type="button"
            className="composer-chip"
            disabled={busy || state.conversations.length === 0}
            aria-expanded={workspaceOpen}
            aria-haspopup="listbox"
            title={
              state.conversations.length === 0
                ? "请先在侧边栏新建工作空间"
                : "切换工作空间"
            }
            onClick={() => setWorkspaceOpen((v) => !v)}
          >
            <Icon name="folder-2" size={14} />
            <span className="composer-chip__label">{workspaceLabel}</span>
            <span className="composer-chip__chevron" aria-hidden="true" />
          </button>
          {workspaceOpen && (
            <div
              className="composer-workspace-menu"
              role="listbox"
              aria-label="工作空间"
            >
              {state.conversations.length === 0 ? (
                <div className="composer-workspace-menu__empty">
                  请先在侧边栏新建工作空间
                </div>
              ) : (
                state.conversations.map((conv) => {
                  const selected = conv.id === state.currentConversationId;
                  const ws = folderName(conv.workspaceDir);
                  const task = conv.title?.trim() || "Agent 任务";
                  const label = conv.workspaceDir ? `${ws} · ${task}` : task;
                  return (
                    <button
                      key={conv.id}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      className={`composer-workspace-menu__item${
                        selected ? " is-selected" : ""
                      }`}
                      onClick={() => switchWorkspace(conv.id)}
                    >
                      <Icon name="folder-2" size={14} />
                      <span className="composer-workspace-menu__text">
                        <span className="composer-workspace-menu__name">
                          {label}
                        </span>
                        {conv.workspaceDir && (
                          <span className="composer-workspace-menu__path">
                            {conv.workspaceDir}
                          </span>
                        )}
                      </span>
                      {selected && (
                        <span className="composer-workspace-menu__check">✓</span>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          )}
        </div>

        <div className="composer-status__right">
          {state.solveProgress.active && (
            <span
              className="composer-solve-progress"
              title={state.solveProgress.message || "求解进行中"}
              role="status"
              aria-live="polite"
            >
              <span className="composer-solve-progress__bar" aria-hidden>
                <span
                  className="composer-solve-progress__fill"
                  style={{
                    width: `${Math.max(4, Math.min(100, state.solveProgress.percent || 0))}%`,
                  }}
                />
              </span>
              <span className="composer-solve-progress__text">
                {Math.round(state.solveProgress.percent || 0)}%
                {state.solveProgress.message
                  ? ` · ${state.solveProgress.message}`
                  : " · 求解中"}
              </span>
            </span>
          )}
          <button
            type="button"
            className={`composer-compute-badge is-${state.computeBackend.mode} is-pref-${computePref}`}
            title={`${computePrefMeta.hint}\n点击切换：自动 → 仅 CPU → 优先 GPU`}
            disabled={busy}
            onClick={() => void cycleComputePreference()}
          >
            <span className="composer-compute-badge__dot" aria-hidden />
            <span className="composer-compute-badge__label">
              {busy || state.solveProgress.active
                ? state.computeBackend.label
                : `计算 · ${computePrefMeta.label}`}
            </span>
          </button>
          <span
            className="composer-token-meter"
            title={
              tokenStats.calls > 0
                ? `本会话 LLM：输入 ${tokenStats.prompt.toLocaleString("zh-CN")} · 输出 ${tokenStats.completion.toLocaleString("zh-CN")} · 合计 ${tokenStats.total.toLocaleString("zh-CN")} · ${tokenStats.calls} 次调用`
                : "本会话尚未产生 token 用量"
            }
          >
            <span className="composer-token-meter__label">tokens</span>
            <span className="composer-token-meter__value">
              {formatTokenCount(tokenStats.total)}
              {tokenStats.calls > 0
                ? ` · in ${formatTokenCount(tokenStats.prompt)} / out ${formatTokenCount(tokenStats.completion)}`
                : ""}
            </span>
          </span>
          <ModelPicker
            apiKey={deepseek.api_key}
            model={deepseek.model}
            disabled={busy}
            variant="composer"
            onSelect={selectModel}
          />
        </div>
      </div>
    </div>
  );
}
