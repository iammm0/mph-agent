import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../lib/types";
import { useAppState } from "../context/AppStateContext";
import { useBridge } from "../hooks/useBridge";

interface UserMessageProps {
  message: ChatMessage;
  messageIndex: number;
}

export function UserMessage({ message, messageIndex }: UserMessageProps) {
  const { state, dispatch } = useAppState();
  const { handleSubmit } = useBridge();
  const [selected, setSelected] = useState(false);
  const [copied, setCopied] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const busy = state.busyConversationId != null;

  useEffect(() => {
    if (!selected) return;
    const onDocMouseDown = (event: MouseEvent) => {
      const el = rootRef.current;
      if (el && !el.contains(event.target as Node)) {
        setSelected(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [selected]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const handleCopy = useCallback(async () => {
    const text = message.text ?? "";
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }, [message.text]);

  const handleEdit = useCallback(() => {
    dispatch({
      type: "SET_EDITING_DRAFT",
      text: message.text,
      resumeFromIndex: messageIndex,
    });
    setSelected(false);
    window.requestAnimationFrame(() => {
      const el = document.querySelector<HTMLTextAreaElement>(".prompt-input");
      el?.focus();
      el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, [dispatch, message.text, messageIndex]);

  const handleResend = useCallback(() => {
    if (busy) return;
    const cid = state.currentConversationId;
    const text = (message.text || "").trim();
    if (!cid || !text) return;
    dispatch({
      type: "REMOVE_MESSAGES_FROM_INDEX",
      conversationId: cid,
      fromIndex: messageIndex,
    });
    dispatch({ type: "CLEAR_EDIT_RESUME" });
    setSelected(false);
    handleSubmit(text);
  }, [
    busy,
    dispatch,
    handleSubmit,
    message.text,
    messageIndex,
    state.currentConversationId,
  ]);

  return (
    <div
      ref={rootRef}
      className={`user-msg${selected ? " user-msg--selected" : ""}`}
      onClick={() => setSelected(true)}
      role="group"
      aria-label="用户消息"
    >
      <div className="user-msg-text">{message.text}</div>
      <div className={`user-msg-actions${selected ? " is-visible" : ""}`}>
        <button
          type="button"
          className="user-msg-action"
          onClick={(event) => {
            event.stopPropagation();
            void handleCopy();
          }}
          title="一键复制"
        >
          {copied ? "已复制" : "复制"}
        </button>
        <button
          type="button"
          className="user-msg-action"
          onClick={(event) => {
            event.stopPropagation();
            handleEdit();
          }}
          title="重新编辑到输入框"
        >
          重新编辑
        </button>
        <button
          type="button"
          className="user-msg-action user-msg-action--primary"
          disabled={busy}
          onClick={(event) => {
            event.stopPropagation();
            handleResend();
          }}
          title={busy ? "当前有任务执行中" : "从该条重新发送"}
        >
          重新发送
        </button>
      </div>
    </div>
  );
}
