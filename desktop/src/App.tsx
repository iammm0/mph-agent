import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useAppState } from "./context/AppStateContext";
import { Sidebar } from "./components/Sidebar";
import { Session } from "./components/Session";
import { TitleBar } from "./components/TitleBar";
import { DialogOverlay } from "./components/dialogs/DialogOverlay";
import { HelpDialog } from "./components/dialogs/HelpDialog";
import { BackendDialog } from "./components/dialogs/BackendDialog";
import { ContextDialog } from "./components/dialogs/ContextDialog";
import { ExecDialog } from "./components/dialogs/ExecDialog";
import { OutputDialog } from "./components/dialogs/OutputDialog";
import { SettingsDialog } from "./components/dialogs/SettingsDialog";
import { ApiBrowserDialog } from "./components/dialogs/ApiBrowserDialog";
import { PlanQuestionsDialog } from "./components/dialogs/PlanQuestionsDialog";
import { MphbPreviewDialog } from "./components/dialogs/MphbPreviewDialog";

interface BridgeInitStatus {
  ready: boolean;
  error: string | null;
  initializing?: boolean;
}


export default function App() {
  const { state, dispatch } = useAppState();
  const [bridgeStatus, setBridgeStatus] = useState<BridgeInitStatus | null>(null);

  const refreshBridgeStatus = useCallback(async (ensureReady = false) => {
    const command = ensureReady ? "bridge_ensure_ready" : "bridge_init_status";
    try {
      const res = await invoke<{ ready: boolean; error: string | null; initializing?: boolean }>(command);
      setBridgeStatus({
        ready: res.ready,
        error: res.error ?? null,
        initializing: res.initializing ?? false,
      });
    } catch {
      setBridgeStatus({ ready: false, error: "无法获取 Bridge 状态", initializing: false });
    }
  }, []);

  const closeDialog = useCallback(() => {
    dispatch({ type: "SET_DIALOG", dialog: null });
  }, [dispatch]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && state.activeDialog) {
        closeDialog();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [state.activeDialog, closeDialog]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    invoke("apply_window_icon").catch(() => {});
  }, []);

  useEffect(() => {
    void refreshBridgeStatus(true);
  }, [refreshBridgeStatus]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    const openMphb = (path: string) => {
      const p = (path || "").trim();
      if (!p.toLowerCase().endsWith(".mphb")) return;
      dispatch({ type: "SET_MPHB_PREVIEW", path: p, openDialog: true });
    };
    void invoke<string | null>("cli_open_path")
      .then((p) => {
        if (p) openMphb(p);
      })
      .catch(() => {});
    void listen<string>("open-mphb", (event) => {
      openMphb(event.payload);
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      unlisten?.();
    };
  }, [dispatch]);

  const dialogContent = (() => {
    switch (state.activeDialog) {
      case "help":
        return <HelpDialog />;
      case "backend":
        return <BackendDialog onClose={closeDialog} />;
      case "context":
        return <ContextDialog onClose={closeDialog} />;
      case "exec":
        return <ExecDialog onClose={closeDialog} />;
      case "output":
        return <OutputDialog onClose={closeDialog} />;
      case "api":
        return <ApiBrowserDialog onClose={closeDialog} />;
      case "planQuestions":
        return <PlanQuestionsDialog onClose={closeDialog} />;
      case "mphbPreview":
        return <MphbPreviewDialog onClose={closeDialog} />;
      default:
        return null;
    }
  })();

  return (
    <div className="app">
      <TitleBar />
      {bridgeStatus && !bridgeStatus.ready && bridgeStatus.error && (
        <div className="bridge-error-banner" role="alert">
          <div className="bridge-error-main">
            <span>Bridge 未就绪：{bridgeStatus.error}</span>
            <span className="bridge-error-hint">
              应用启动时会自动重建 Bridge。若本次启动仍失败，可直接重试，无需重开整个桌面端。
            </span>
          </div>
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={() => void refreshBridgeStatus(true)}
          >
            重试启动 Bridge
          </button>
        </div>
      )}
      <div className="app-body">
        {state.view === "session" ? (
          <>
            <Sidebar />
            <div className="app-main">
              <Session />
            </div>
          </>
        ) : (
          <div className="app-main">
            <SettingsDialog pageMode />
          </div>
        )}
      </div>
      {dialogContent && (
        <DialogOverlay onClose={closeDialog} dialogType={state.activeDialog}>
          {dialogContent}
        </DialogOverlay>
      )}
    </div>
  );
}
