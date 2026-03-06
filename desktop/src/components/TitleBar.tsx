import { useCallback } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

const WIN_CONTROL_CLASS = "titlebar-win-control";

export function TitleBar() {
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
        <span className="titlebar-icon" aria-hidden>◇</span>
        <span className="titlebar-title">Multiphysics Modeling Agent</span>
      </div>
      <div className="titlebar-right">
        <button
          type="button"
          className={WIN_CONTROL_CLASS}
          onClick={handleMinimize}
          title="最小化"
          aria-label="最小化"
        >
          <span className="titlebar-btn-icon">−</span>
        </button>
        <button
          type="button"
          className={WIN_CONTROL_CLASS}
          onClick={handleToggleMaximize}
          title="最大化 / 还原"
          aria-label="最大化"
        >
          <span className="titlebar-btn-icon">□</span>
        </button>
        <button
          type="button"
          className={`${WIN_CONTROL_CLASS} titlebar-close`}
          onClick={handleClose}
          title="关闭"
          aria-label="关闭"
        >
          <span className="titlebar-btn-icon">×</span>
        </button>
      </div>
    </div>
  );
}
