import { useEffect, useMemo, useState } from "react";
import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";
import { sanitizeLLMDisplayText } from "../../lib/textSanitizer";

/** 从事件中抽出可展示的「模型思考 / 推理」正文 */
export function extractThinkingText(events: RunEvent[] | undefined): string {
  if (!events?.length) return "";
  const parts: string[] = [];
  let streamBuf = "";
  let streamKind = "";

  const flushStream = () => {
    const text = sanitizeLLMDisplayText(streamBuf).trim();
    if (text) parts.push(text);
    streamBuf = "";
    streamKind = "";
  };

  for (const event of events) {
    if (event.type === "llm_stream_chunk") {
      const kind = String(event.data?.kind ?? "content");
      const chunk = String(event.data?.chunk ?? event.data?.text ?? "");
      const phase = String(event.data?.phase ?? "");
      // Cursor 式 thinking：只收模型 reasoning 通道，或显式 thinking 阶段
      const isReasoning = kind === "reasoning" || phase === "thinking";
      if (!isReasoning) {
        flushStream();
        continue;
      }
      if (streamBuf && streamKind && streamKind !== kind) flushStream();
      streamKind = kind || "reasoning";
      streamBuf += chunk;
      continue;
    }

    flushStream();

    if (event.type === "think_chunk") {
      const thought = event.data?.thought as Record<string, unknown> | undefined;
      const reasoning = sanitizeLLMDisplayText(
        String(
          thought?.reasoning ??
            event.data?.chunk ??
            event.data?.text ??
            ""
        )
      ).trim();
      if (reasoning) parts.push(reasoning);
      continue;
    }

    if (event.type === "decision") {
      const reasoning = sanitizeLLMDisplayText(
        String(event.data?.reasoning ?? "")
      ).trim();
      if (reasoning) parts.push(reasoning);
    }
  }

  flushStream();

  // 去重相邻重复段，避免 plan 流与 think_chunk 重复贴两次
  const deduped: string[] = [];
  for (const part of parts) {
    if (deduped.length && deduped[deduped.length - 1] === part) continue;
    deduped.push(part);
  }
  return deduped.join("\n\n").trim();
}

function formatThoughtDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return "不到 1 秒";
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec} 秒`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m} 分 ${s} 秒` : `${m} 分`;
}

export function ThinkingDisclosure({
  text,
  isLive = false,
  durationMs,
}: {
  text: string;
  isLive?: boolean;
  durationMs?: number | null;
}) {
  const cleaned = useMemo(() => sanitizeLLMDisplayText(text).trim(), [text]);
  const [open, setOpen] = useState(isLive);
  const [userTouched, setUserTouched] = useState(false);

  useEffect(() => {
    if (userTouched) return;
    setOpen(isLive);
  }, [isLive, userTouched]);

  if (!cleaned && !isLive) return null;

  const durationLabel = formatThoughtDuration(durationMs);
  const summary = isLive
    ? "思考中"
    : durationLabel
      ? `已思考 ${durationLabel}`
      : "思考过程";

  return (
    <div
      className={`thinking-disclosure${open ? " is-open" : ""}${
        isLive ? " is-live" : ""
      }`}
    >
      <button
        type="button"
        className="thinking-disclosure__toggle"
        onClick={() => {
          setUserTouched(true);
          setOpen((v) => !v);
        }}
        aria-expanded={open}
      >
        <span className="thinking-disclosure__chevron" aria-hidden>
          <Icon name={open ? "arrow-down-01" : "arrow-right-01"} size={14} />
        </span>
        <span className="thinking-disclosure__label">{summary}</span>
        {isLive ? (
          <span className="thinking-disclosure__live-dot" aria-hidden />
        ) : null}
      </button>
      {open && (
        <div className="thinking-disclosure__body" role="region" aria-label="思考过程">
          {cleaned || (isLive ? "…" : "")}
          {isLive ? <span className="thinking-disclosure__caret" aria-hidden /> : null}
        </div>
      )}
    </div>
  );
}
