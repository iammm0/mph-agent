import { useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useAppState } from "../context/AppStateContext";
import { loadApiConfig, getPayloadFromConfig } from "../lib/apiConfig";
import type {
  RunEvent,
  BridgeResponse,
  ClarifyingQuestion,
  PromptExtensionName,
} from "../lib/types";
import { normalizeClarifyingQuestions } from "../lib/clarifying";

function extractClarifyingQuestionsFromResponse(
  res: BridgeResponse
): ClarifyingQuestion[] {
  const topLevel = normalizeClarifyingQuestions(res.clarifying_questions);
  if (topLevel.length > 0) return topLevel;

  const planQuestions = normalizeClarifyingQuestions(
    (res.plan as Record<string, unknown> | null | undefined)?.clarifying_questions
  );
  return planQuestions;
}

function extractUnresolvedClarificationCount(res: BridgeResponse): number {
  const unresolved = (res.plan as Record<string, unknown> | null | undefined)
    ?.unresolved_clarifications;
  return Array.isArray(unresolved) ? unresolved.length : 0;
}

export function useBridge() {
  const { state, dispatch, addMessage, messages } = useAppState();
  const cid = state.currentConversationId;
  const abortedRef = useRef(false);

  const applyModeResponseSideEffects = useCallback(
    (cmd: string, res: BridgeResponse) => {
      if (cmd === "plan" || cmd === "chat") {
        const questions = extractClarifyingQuestionsFromResponse(res);
        const unresolvedCount = extractUnresolvedClarificationCount(res);
        const needsClarification =
          Boolean(res.plan_needs_clarification) ||
          unresolvedCount > 0 ||
          (questions.length > 0 && !Boolean(res.plan_confirmed));

        if (needsClarification && questions.length > 0) {
          dispatch({ type: "SET_MODE", mode: "plan" });
          dispatch({ type: "SET_PLAN_QUESTIONS", questions });
          dispatch({ type: "SET_DIALOG", dialog: "planQuestions" });
        } else {
          dispatch({ type: "CLEAR_PLAN_QUESTIONS" });
          if (cmd === "chat" && Boolean(res.plan_confirmed)) {
            dispatch({ type: "SET_MODE", mode: "run" });
          }
        }
      }
    },
    [dispatch]
  );

  const sendCommand = useCallback(
    async (cmd: string, payload: Record<string, unknown> = {}) => {
      if (!cid) return;
      dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: cid });
      try {
        const res = await invoke<BridgeResponse>("bridge_send", {
          cmd,
          payload: {
            ...payload,
            conversation_id: cid,
            workspace_dir: state.workspaceDir ?? undefined,
          },
        });
        applyModeResponseSideEffects(cmd, res);
        addMessage("assistant", res.message, {
          success: res.ok,
          caseData: res.case_generated ?? null,
          caseSavedPath: res.saved_path ?? null,
          assistantPresentation:
            cmd === "doctor" ? "environment_diagnosis" : undefined,
        });
        return res;
      } catch (e) {
        addMessage("assistant", "请求失败: " + String(e), { success: false });
        return null;
      } finally {
        dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: null });
      }
    },
    [cid, state.workspaceDir, dispatch, addMessage, applyModeResponseSideEffects]
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
        const payload = event.payload;
        dispatch({ type: "APPEND_EVENT", conversationId: cid, event: payload });

        if (payload.type === "task_phase") {
          const phase = String(
            (payload.data as Record<string, unknown> | undefined)?.phase ?? ""
          ).toLowerCase();
          if (phase === "discussion" || phase === "discuss") {
            dispatch({ type: "SET_MODE", mode: "discuss" });
          } else if (phase === "planning" || phase === "plan") {
            dispatch({ type: "SET_MODE", mode: "plan" });
          } else if (phase === "running" || phase === "run" || phase === "execute") {
            dispatch({ type: "SET_MODE", mode: "run" });
          }
        }

        if (payload.type !== "plan_end") return;

        const data = payload.data ?? {};
        const questionsRaw =
          (data as Record<string, unknown>).clarifying_questions ??
          (data as Record<string, unknown>).questions;
        const questions = normalizeClarifyingQuestions(questionsRaw);
        const unresolved = (data as Record<string, unknown>)
          .unresolved_clarifications;
        const unresolvedCount = Array.isArray(unresolved) ? unresolved.length : 0;
        const requiresClarification =
          Boolean((data as Record<string, unknown>).requires_clarification) ||
          unresolvedCount > 0 ||
          questions.length > 0;

        if (requiresClarification && questions.length > 0) {
          dispatch({ type: "SET_PLAN_QUESTIONS", questions });
          dispatch({ type: "SET_DIALOG", dialog: "planQuestions" });
        }
      });

      try {
        const res = await invoke<BridgeResponse>("bridge_send_stream", {
          cmd,
          payload: {
            ...payload,
            conversation_id: cid,
            stream: true,
            workspace_dir: state.workspaceDir ?? undefined,
          },
        });
        applyModeResponseSideEffects(cmd, res);
        dispatch({
          type: "FINALIZE_LAST",
          conversationId: cid,
          text: res.message,
          success: res.ok,
        });
        return res;
      } catch (e) {
        if (!abortedRef.current) {
          dispatch({
            type: "FINALIZE_LAST",
            conversationId: cid,
            text: "请求失败: " + String(e),
            success: false,
          });
        }
        return null;
      } finally {
        unlisten();
        dispatch({ type: "SET_BUSY_CONVERSATION", conversationId: null });
      }
    },
    [cid, state.workspaceDir, dispatch, applyModeResponseSideEffects]
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

  const triggerExtensionAction = useCallback(
    async (
      name: PromptExtensionName,
      options?: {
        modelPath?: string;
      }
    ) => {
      if (!cid && name !== "exit" && name !== "help") return;

      switch (name) {
        case "exit":
          window.close();
          return;
        case "help":
          dispatch({ type: "SET_DIALOG", dialog: "help" });
          return;
        case "api":
          dispatch({ type: "SET_DIALOG", dialog: "api" });
          return;
        case "backend":
          dispatch({ type: "SET_DIALOG", dialog: "backend" });
          return;
        case "context":
          dispatch({ type: "SET_DIALOG", dialog: "context" });
          return;
        case "exec":
          dispatch({ type: "SET_DIALOG", dialog: "exec" });
          return;
        case "output":
          dispatch({ type: "SET_DIALOG", dialog: "output" });
          return;
        case "demo":
          addMessage("system", "已触发牛顿环仿真示例");
          await sendCommand("demo");
          return;
        case "doctor":
          addMessage("system", "正在执行环境诊断");
          await sendCommand("doctor");
          return;
        case "case": {
          const modelPath = options?.modelPath?.trim();
          if (!modelPath) {
            addMessage("system", "未选择 .mph 文件", { success: false });
            return;
          }
          addMessage("system", `读取案例文件：${modelPath}`);
          await sendCommand("case", { model_path: modelPath });
          return;
        }
        default:
          return;
      }
    },
    [cid, dispatch, addMessage, sendCommand]
  );

  const handleSubmit = useCallback(
    (raw: string) => {
      const line = raw.trim();
      if (!line || !cid) return;

      addMessage("user", line);
      dispatch({ type: "SET_LAST_PLAN_INPUT", input: line });

      const userCount = messages.filter((m) => m.role === "user").length;
      void (async () => {
        const apiPayload = getPayloadFromConfig(state.backend, loadApiConfig());

        if (userCount <= 1) {
          try {
            const res = await invoke<{
              ok: boolean;
              message: string;
              title?: string;
            }>("bridge_send", {
              cmd: "conversation_title_suggest",
              payload: {
                input: line,
                ...apiPayload,
              },
            });
            const suggested = (res.title ?? res.message ?? "").trim();
            if (suggested) {
              dispatch({
                type: "SET_CONVERSATION_TITLE",
                id: cid,
                title: suggested,
              });
            }
          } catch {
            const fallback = line.length > 50 ? line.slice(0, 47) + "..." : line;
            dispatch({ type: "SET_CONVERSATION_TITLE", id: cid, title: fallback });
          }
        }

        await sendStreamCommand("chat", {
          input: line,
          output: state.outputDefault ?? undefined,
          workspace_dir: state.workspaceDir ?? undefined,
          ...apiPayload,
        });
      })();
    },
    [
      cid,
      state.outputDefault,
      state.workspaceDir,
      state.backend,
      messages,
      dispatch,
      addMessage,
      sendStreamCommand,
    ]
  );

  return {
    handleSubmit,
    sendCommand,
    sendStreamCommand,
    abortRun,
    triggerExtensionAction,
  };
}
