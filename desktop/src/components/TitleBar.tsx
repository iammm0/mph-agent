import { useCallback } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useAppState } from "../context/AppStateContext";
import { getProviderLabel } from "../lib/apiConfig";
import type { AppView } from "../lib/types";
import { Icon } from "./Icon";

const WIN_CONTROL_CLASS = "titlebar-win-control";

const NAV_ITEMS: Array<{ view: AppView; label: string; icon: string }> = [
  { view: "session", label: "对话", icon: "messages" },
  { view: "case-library", label: "案例库", icon: "book" },
  { view: "skills-system", label: "技能系统", icon: "flash" },
  { view: "ops-catalog", label: "操作", icon: "code-1" },
  { view: "settings", label: "设置", icon: "setting-2" },
];

export function TitleBar() {
  const { dispatch, sessionTitle, messages, state } = useAppState();
  const backendLabel = getProviderLabel(state.backend);

  const handleMinimize = useCallback(() => {
    getCurrentWindow().minimize();
  }, []);

  const handleToggleMaximize = useCallback(() => {
    getCurrentWindow().toggleMaximize();
  }, []);

  const handleClose = useCallback(() => {
    getCurrentWindow().close();
  }, []);

  return (
    <div className="titlebar">
      <div className="titlebar-left" data-tauri-drag-region>
        <span className="titlebar-icon" aria-hidden>
          <Icon name="3dcube" size={16} />
        </span>
        <span className="titlebar-title">多物理场建模智能体</span>
        <span className="titlebar-session" title={sessionTitle}>
          #{sessionTitle}
        </span>
      </div>
      <div className="titlebar-right">
        <div className="titlebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.view}
              type="button"
              className={`titlebar-entry-btn ${state.view === item.view ? "active" : ""}`}
              onClick={() => dispatch({ type: "SET_VIEW", view: item.view })}
              title={item.label}
              aria-label={item.label}
            >
              <Icon name={item.icon} size={14} />
              <span>{item.label}</span>
            </button>
          ))}
        </div>
        <span className="titlebar-badge" title="当前会话消息数">
          {messages.length} 条消息
        </span>
        <span className="titlebar-badge mode" title="当前模式">
          {state.mode === "discuss" ? "讨论" : state.mode === "plan" ? "规划" : "执行"}
        </span>
        <span className="titlebar-badge backend" title="当前 LLM 后端">
          {backendLabel}
        </span>
        <button
          type="button"
          className={WIN_CONTROL_CLASS}
          onClick={handleMinimize}
          title="最小化"
          aria-label="最小化"
        >
          <Icon name="minus" size={14} />
        </button>
        <button
          type="button"
          className={WIN_CONTROL_CLASS}
          onClick={handleToggleMaximize}
          title="最大化 / 还原"
          aria-label="最大化"
        >
          <Icon name="maximize-3" size={14} />
        </button>
        <button
          type="button"
          className={`${WIN_CONTROL_CLASS} titlebar-close`}
          onClick={handleClose}
          title="关闭"
          aria-label="关闭"
        >
          <Icon name="close-circle" size={14} />
        </button>
      </div>
    </div>
  );
}
