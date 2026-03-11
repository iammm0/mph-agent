import { useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useAppState } from "../context/AppStateContext";
import { loadApiConfig, getPayloadFromConfig } from "../lib/apiConfig";
import type { RunEvent, BridgeResponse } from "../lib/types";

export function useBridge() {
  const { state, dispatch, addMessage, messages } = useAppState();
  const cid = state.currentConversationId;
  const abortedRef = useRef(false);

  const sendCommand = useCallback(
    async (cmd: string, payload: Record<string, unknown> = {}) => {
      if (!cid) return;
      dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: cid });
      try {
        const res = await invoke<BridgeResponse>("bridge_send", {
          cmd,
          payload: { ...payload, conversation_id: cid },
        });
        addMessage("assistant", res.message, { success: res.ok });
      } catch (e) {
        addMessage("assistant", "请求失败: " + String(e), { success: false });
      } finally {
        dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: null });
      }
    },
    [cid, dispatch, addMessage]
  );

  const sendStreamCommand = useCallback(
    async (cmd: string, payload: Record<string, unknown> = {}) => {
      if (!cid) return;
      abortedRef.current = false;
      dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: cid });
      dispatch({
        type: "ADD_MESSAGE",
        conversationId: cid,
        role: "assistant",
        text: "",
        events: [],
      });

      const unlisten = await listen<RunEvent>("bridge-event", (event) => {
        dispatch({ type: "APPEND_EVENT", conversationId: cid, event: event.payload });
      });

      try {
        const res = await invoke<BridgeResponse>("bridge_send_stream", {
          cmd,
          payload: { ...payload, conversation_id: cid },
        });
        dispatch({
          type: "FINALIZE_LAST",
          conversationId: cid,
          text: res.message,
          success: res.ok,
        });
        // 若仅生成 Plan 且需要澄清问题，则由 PLAN_END 事件驱动对话框，消息文本保持简短提示
      } catch (e) {
        if (!abortedRef.current) {
          dispatch({
            type: "FINALIZE_LAST",
            conversationId: cid,
            text: "请求失败: " + String(e),
            success: false,
          });
        }
      } finally {
        unlisten();
        dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: null });
      }
    },
    [cid, dispatch]
  );

  const abortRun = useCallback(async () => {
    const busyId = state.busyConversationId;
    if (!busyId) return;
    abortedRef.current = true;
    try {
      await invoke("bridge_abort");
    } catch (_) {}
    dispatch({
      type: "FINALIZE_LAST",
      conversationId: busyId,
      text: "已取消",
      success: false,
    });
    dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: null });
  }, [state.busyConversationId, dispatch]);

  const handleSubmit = useCallback(
    (raw: string) => {
      const line = raw.trim();
      if (!line) return;
      if (!cid) return;

      if (line.startsWith("/")) {
        const cmd = line.toLowerCase().split(/\s/)[0];
        if (cmd === "/quit" || cmd === "/exit") {
          window.close();
          return;
        }
        if (cmd === "/run") {
          dispatch({ type: "SET_MODE", mode: "run" });
          addMessage("system", "已切换为 Build 模式");
          return;
        }
        if (cmd === "/plan") {
          dispatch({ type: "SET_MODE", mode: "plan" });
          addMessage("system", "已切换为 Plan 模式");
          return;
        }
        if (cmd === "/help") {
          dispatch({ type: "SET_DIALOG", dialog: "help" });
          return;
        }
        if (cmd === "/ops") {
          dispatch({ type: "SET_DIALOG", dialog: "ops" });
          return;
        }
        if (cmd === "/api") {
          dispatch({ type: "SET_DIALOG", dialog: "api" });
          return;
        }
        if (cmd === "/demo") {
          addMessage("user", line);
          sendCommand("demo");
          return;
        }
        if (cmd === "/doctor") {
          addMessage("user", line);
          sendCommand("doctor");
          return;
        }
        if (cmd === "/context") {
          dispatch({ type: "SET_DIALOG", dialog: "context" });
          return;
        }
        if (cmd === "/backend") {
          dispatch({ type: "SET_DIALOG", dialog: "backend" });
          return;
        }
        if (cmd === "/exec") {
          dispatch({ type: "SET_DIALOG", dialog: "exec" });
          return;
        }
        if (cmd === "/output") {
          dispatch({ type: "SET_DIALOG", dialog: "output" });
          return;
        }
        addMessage("system", "未知命令: " + cmd + "，输入 /help 查看帮助", {
          success: false,
        });
        return;
      }

      addMessage("user", line);
      // 记录本次用于触发 /run 的用户输入，供 PlanQuestionsDialog 二次调用使用
      dispatch({ type: "SET_LAST_PLAN_INPUT", input: line });

      const userCount = messages.filter((m) => m.role === "user").length;
      if (userCount <= 1) {
        const title = line.length > 50 ? line.slice(0, 47) + "..." : line;
        dispatch({ type: "SET_CONVERSATION_TITLE", id: cid, title });
      }

      if (state.mode === "plan") {
        const apiPayload = getPayloadFromConfig(state.backend, loadApiConfig());
        sendCommand("plan", { input: line, ...apiPayload });
      } else {
        const apiPayload = getPayloadFromConfig(state.backend, loadApiConfig());
        sendStreamCommand("run", {
          input: line,
          output: state.outputDefault ?? undefined,
          backend: state.backend ?? undefined,
          use_react: true,
          no_context: false,
          ...apiPayload,
        });
      }
    },
    [cid, state.mode, state.outputDefault, state.backend, messages, dispatch, addMessage, sendCommand, sendStreamCommand]
  );

  return { handleSubmit, sendCommand, sendStreamCommand, abortRun };
}
