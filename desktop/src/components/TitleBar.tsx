import { useCallback } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { BrandLockup } from "./Logo";
import { Icon } from "./Icon";

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
        <BrandLockup size={18} />
      </div>
      <div className="titlebar-right">
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
