import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
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
import { ComsolOpsDialog } from "./components/dialogs/ComsolOpsDialog";

interface BridgeInitStatus {
  ready: boolean;
  error: string | null;
}

export default function App() {
  const { state, dispatch } = useAppState();
  const [bridgeStatus, setBridgeStatus] = useState<BridgeInitStatus | null>(null);

  const closeDialog = useCallback(() => {
    dispatch({ type: "SET_DIALOG", dialog: null });
  }, [dispatch]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && state.activeDialog) {
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
    invoke<{ ready: boolean; error: string | null }>("bridge_init_status")
      .then((res) => setBridgeStatus({ ready: res.ready, error: res.error ?? null }))
      .catch(() => setBridgeStatus({ ready: false, error: "无法获取 Bridge 状态" }));
  }, []);

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
      case "ops":
        return <ComsolOpsDialog onClose={closeDialog} />;
      case "settings":
        return <SettingsDialog onClose={closeDialog} />;
      default:
        return null;
    }
  })();

  return (
    <div className="app">
      <TitleBar />
      {bridgeStatus && !bridgeStatus.ready && bridgeStatus.error && (
        <div className="bridge-error-banner" role="alert">
          Bridge 未就绪：{bridgeStatus.error}
          <span className="bridge-error-hint">
            请从项目根目录启动应用，或设置 MPH_AGENT_BRIDGE_DEBUG=1 后查看 %TEMP%\mph-agent-bridge-debug.log
          </span>
        </div>
      )}
      <div className="app-body">
        <Sidebar />
        <div className="app-main">
          <Session />
        </div>
      </div>
      {dialogContent && (
        <DialogOverlay onClose={closeDialog}>{dialogContent}</DialogOverlay>
      )}
    </div>
  );
}
