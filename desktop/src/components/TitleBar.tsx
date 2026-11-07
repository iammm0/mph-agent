import { useCallback, useEffect, useState } from "react";
import { getCurrentWindow, type Window } from "@tauri-apps/api/window";
import { BrandLockup } from "./Logo";
import { Icon } from "./Icon";

const WIN_CONTROL_CLASS = "titlebar-win-control";

function tryGetCurrentWindow(): Window | null {
  try {
    return getCurrentWindow();
  } catch {
    return null;
  }
}

/** Windows 风格：单方框 = 最大化；重叠方框 = 还原（不再用向外展开的 maximize-3） */
function MaximizeGlyph({ restored }: { restored: boolean }) {
  if (restored) {
    return (
      <svg
        width="12"
        height="12"
        viewBox="0 0 12 12"
        aria-hidden="true"
        className="titlebar-win-glyph"
      >
        <rect
          x="3.5"
          y="1.5"
          width="7"
          height="7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
        />
        <rect
          x="1.5"
          y="3.5"
          width="7"
          height="7"
          fill="var(--bg-panel, #fff)"
          stroke="currentColor"
          strokeWidth="1.2"
        />
      </svg>
    );
  }
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      aria-hidden="true"
      className="titlebar-win-glyph"
    >
      <rect
        x="2"
        y="2"
        width="8"
        height="8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
    </svg>
  );
}

export function TitleBar() {
  const [maximized, setMaximized] = useState(false);

  const syncMaximized = useCallback(async () => {
    const win = tryGetCurrentWindow();
    if (!win) return;
    try {
      setMaximized(await win.isMaximized());
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    const win = tryGetCurrentWindow();
    if (!win) return;

    const unsubs: Array<() => void> = [];
    void syncMaximized();

    void win
      .onResized(() => {
        void syncMaximized();
      })
      .then((fn) => unsubs.push(fn))
      .catch(() => {});

    void win
      .onMoved(() => {
        void syncMaximized();
      })
      .then((fn) => unsubs.push(fn))
      .catch(() => {});

    return () => {
      for (const unsub of unsubs) unsub();
    };
  }, [syncMaximized]);

  const handleMinimize = useCallback(() => {
    void tryGetCurrentWindow()?.minimize();
  }, []);

  const handleToggleMaximize = useCallback(async () => {
    const win = tryGetCurrentWindow();
    if (!win) return;
    setMaximized((prev) => !prev);
    try {
      await win.toggleMaximize();
    } catch {
      // ignore
    }
    window.setTimeout(() => {
      void win.isMaximized().then(setMaximized).catch(() => {});
    }, 80);
  }, []);

  const handleClose = useCallback(() => {
    void tryGetCurrentWindow()?.close();
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
          onClick={() => void handleToggleMaximize()}
          title={maximized ? "还原" : "最大化"}
          aria-label={maximized ? "还原" : "最大化"}
        >
          <MaximizeGlyph restored={maximized} />
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
