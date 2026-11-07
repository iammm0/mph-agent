import { useMemo } from "react";
import type { ChatMessage } from "../lib/types";
import { ReasoningStream } from "./run-events/ReasoningStream";
import { invoke } from "@tauri-apps/api/core";
import { useAppState } from "../context/AppStateContext";
import { useBridge } from "../hooks/useBridge";
import type { RunEvent } from "../lib/types";
import { MarkdownContent } from "./MarkdownContent";
import { sanitizeLLMDisplayText } from "../lib/textSanitizer";
import { CaseAnalysisCard } from "./CaseAnalysisCard";
import { parseStructuredAssistantText } from "../lib/structuredAssistantMessage";
import {
  isEnvironmentDiagnosisMessage,
  parseDoctorReportText,
} from "../lib/parseDoctorReport";
import { DoctorDiagnosisCard } from "./DoctorDiagnosisCard";
import { ReasoningLivePlaceholder } from "./ReasoningLivePlaceholder";
import {
  extractNextActionsFromEvents,
  NextActionsCard,
} from "./run-events/NextActionsCard";

/** 合并连续的 llm_stream_chunk 为单条，便于展示完整思维过程 */
function mergeStreamChunks(events: RunEvent[]): RunEvent[] {
  const out: RunEvent[] = [];
  let buf = "";
  let phase = "";
  for (const e of events) {
    if (e.type === "llm_stream_chunk") {
      buf += (e.data?.chunk ?? e.data?.text ?? "") as string;
      phase = (e.data?.phase ?? phase) as string;
      continue;
    }
    if (buf) {
      out.push({ _event: true, type: "llm_stream_chunk", data: { phase, chunk: buf, text: buf } });
      buf = "";
    }
    out.push(e);
  }
  if (buf) out.push({ _event: true, type: "llm_stream_chunk", data: { phase, chunk: buf, text: buf } });
  return out;
}

/** 根据事件列表得到当前阶段文案（用于“处理中”时的具体状态） */
function getPhaseLabel(events: RunEvent[] | undefined): string {
  if (!events?.length) return "处理中";
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    if (ev?.type === "task_phase" && ev?.data?.phase) {
      const map: Record<string, string> = {
        planning: "规划中",
        scanning_capabilities: "扫描能力中",
        thinking: "思考中",
        planning_steps: "排布步骤中",
        executing: "执行中",
        observing: "观察中",
        iterating: "根据结果调整中",
        discussion: "探讨中",
        plan_confirmed: "计划已确认",
        qa: "问答中",
      };
      return map[ev.data.phase as string] ?? "处理中";
    }
  }
  return "处理中";
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function extractModelPath(text: string): string | null {
  if (!text) return null;
  const partialIndex = text.lastIndexOf("模型已部分生成:");
  const fullIndex = text.lastIndexOf("模型已生成:");
  const idx = partialIndex >= 0 ? partialIndex : fullIndex;
  if (idx < 0) return null;
  const slice = text.slice(idx).replace(/^.*模型已(部分)?生成:\s*/, "").trim();
  return slice || null;
}

function extractStreamedAssistantText(events: RunEvent[] | undefined): string {
  if (!events?.length) return "";
  let out = "";
  for (const e of events) {
    if (e.type !== "llm_stream_chunk") continue;
    const chunk = (e.data?.chunk ?? e.data?.text ?? "") as string;
    if (chunk) out += chunk;
  }
  return sanitizeLLMDisplayText(out);
}

function hasDiscussionStream(events: RunEvent[] | undefined): boolean {
  if (!events?.length) return false;
  return events.some((event) => {
    if (event.type === "task_phase" && event.data?.phase === "discussion") {
      return true;
    }
    if (
      event.type === "llm_stream_chunk" &&
      typeof event.data?.phase === "string" &&
      event.data.phase === "discussion"
    ) {
      return true;
    }
    return false;
  });
}

function openInFolder(path: string) {
  invoke("open_in_folder", { path }).catch(() => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(path);
      alert("已复制路径到剪贴板");
    }
  });
}

function openPreviewMd(modelPath: string) {
  const dir = modelPath.replace(/[/\\][^/\\]*$/, "") || modelPath;
  const mdPath = (dir.endsWith("/") || dir.endsWith("\\") ? dir : dir + "/") + "operations.md";
  invoke("open_path", { path: mdPath }).catch(() => {
    alert("未找到操作记录文件 operations.md，请确认模型所在目录。");
  });
}

export function AssistantMessage({ message }: { message: ChatMessage }) {
  const { state } = useAppState();
  const { handleSubmit } = useBridge();
  const hasEvents = (message.events?.length ?? 0) > 0;
  const isError = message.success === false;
  const isCurrentBusy = state.busyConversationId === state.currentConversationId;
  const caseData = message.caseData ?? null;
  const streamedText = extractStreamedAssistantText(message.events);
  const isDiscussionReply = hasDiscussionStream(message.events);
  const structured = useMemo(
    () => parseStructuredAssistantText(message.text || ""),
    [message.text]
  );
  const doctorReport = useMemo(
    () => parseDoctorReportText(message.text || ""),
    [message.text]
  );
  const showDoctorUi = isEnvironmentDiagnosisMessage(
    message.text || "",
    message.assistantPresentation
  );
  const bubbleSourceText = structured?.text ?? message.text ?? "";
  const renderText =
    sanitizeLLMDisplayText(bubbleSourceText) || (isCurrentBusy ? streamedText : "");
  const showText =
    !showDoctorUi &&
    !isError &&
    !isDiscussionReply &&
    !caseData &&
    (Boolean(renderText) || !hasEvents);
  const isStreamingText = Boolean(isCurrentBusy && !message.text && streamedText);
  const modelPath =
    message.modelPath ??
    structured?.modelPath ??
    extractModelPath(message.text || "");
  const phaseLabel = getPhaseLabel(message.events);
  const placeholderText = renderText || (isCurrentBusy ? phaseLabel : "") || "—";
  const showReasoningPanel =
    hasEvents || (isCurrentBusy && !showDoctorUi && !isError);
  const nextActions = useMemo(
    () => extractNextActionsFromEvents(message.events),
    [message.events]
  );
  const showNextActions = Boolean(nextActions && !isCurrentBusy);

  return (
    <div className={`assistant-msg${isCurrentBusy ? " assistant-msg--busy" : ""}`}>
      {isCurrentBusy && (
        <div className="assistant-msg-live-ribbon" aria-hidden>
          <div className="assistant-msg-live-ribbon__bar" />
        </div>
      )}
      <div className="assistant-msg-head">
        <span className="assistant-msg-time">
          {formatTime(message.time ?? Date.now())}
        </span>
      </div>
      {showReasoningPanel && (
        <div className="assistant-msg-reasoning">
          {isCurrentBusy && !hasEvents && (
            <ReasoningLivePlaceholder phaseHint={phaseLabel} />
          )}
          {hasEvents && (
            <div className="assistant-msg-events">
              <ReasoningStream
                events={mergeStreamChunks(message.events!)}
                isLive={isCurrentBusy}
              />
            </div>
          )}
        </div>
      )}
      {showDoctorUi && (
        <DoctorDiagnosisCard
          report={doctorReport}
          rawText={message.text || ""}
          bridgeOk={message.success !== false}
          time={message.time}
        />
      )}
      {isError && !showDoctorUi && (
        <div className="assistant-msg-body error">
          <div className="assistant-msg-text">
            <MarkdownContent
              content={sanitizeLLMDisplayText(bubbleSourceText || message.text || "")}
            />
          </div>
          {modelPath && (
            <div className="assistant-msg-meta">
              <button
                type="button"
                className="assistant-msg-model-btn"
                onClick={() => openInFolder(modelPath)}
                title="打开模型所在目录"
              >
                在文件管理器中打开
              </button>
              <button
                type="button"
                className="assistant-msg-model-btn"
                onClick={() => openPreviewMd(modelPath)}
                title="预览操作记录 (operations.md)"
              >
                预览
              </button>
            </div>
          )}
        </div>
      )}
      {showText && (
        <div className="assistant-msg-body success">
          <div className="assistant-msg-text">
            <MarkdownContent content={placeholderText} />
            {isStreamingText && <span className="assistant-msg-stream-cursor" aria-hidden />}
          </div>
          <div className="assistant-msg-meta">
            {modelPath && (
              <>
                <button
                  type="button"
                  className="assistant-msg-model-btn"
                  onClick={() => openInFolder(modelPath)}
                  title="打开模型所在目录"
                >
                  在文件管理器中打开
                </button>
                <button
                  type="button"
                  className="assistant-msg-model-btn"
                  onClick={() => openPreviewMd(modelPath)}
                  title="预览操作记录 (operations.md)"
                >
                  预览
                </button>
              </>
            )}
            <span className="dot">▣</span>
            <span>{formatTime(message.time ?? Date.now())}</span>
          </div>
        </div>
      )}
      {caseData && !isError && (
        <div className="assistant-msg-body success assistant-msg-body--case">
          <CaseAnalysisCard caseData={caseData} savedPath={message.caseSavedPath} />
        </div>
      )}
      {showNextActions && nextActions && (
        <NextActionsCard
          title={nextActions.title}
          hint={nextActions.hint}
          actions={nextActions.actions}
          disabled={state.busyConversationId != null}
          onSend={(prompt) => handleSubmit(prompt)}
        />
      )}
    </div>
  );
}
