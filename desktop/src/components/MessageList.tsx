import { useEffect, useRef } from "react";
import { useAppState } from "../context/AppStateContext";
import { useBridge } from "../hooks/useBridge";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";
import { SystemMessage } from "./SystemMessage";
import {
  QUICK_PROMPT_GROUPS,
  type QuickPromptGroup,
  type QuickPromptItem,
} from "../lib/types";

const QUICK_PROMPT_ITEMS = QUICK_PROMPT_GROUPS.flatMap((group: QuickPromptGroup) =>
  group.prompts.map((item: QuickPromptItem) => ({
    ...item,
    key: `${group.title}-${item.label}`,
    tip: item.text || group.hint || item.label,
  }))
);

export function MessageList() {
  const { messages, dispatch } = useAppState();
  const { handleSubmit, triggerExtensionAction } = useBridge();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="message-list">
        <div className="message-list-empty">
          <div className="quick-prompts">
            <p className="quick-prompts-title">快速案例</p>
            <p className="quick-prompts-hint">点击即进入执行并开始建模</p>
            <div className="quick-prompts-grid">
              {QUICK_PROMPT_ITEMS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className="quick-prompt-chip"
                  onClick={() => {
                    if (item.extensionName) {
                      void triggerExtensionAction(item.extensionName);
                      return;
                    }
                    dispatch({ type: "SET_MODE", mode: "run" });
                    handleSubmit(item.text);
                  }}
                  title={item.tip}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((msg) => {
        switch (msg.role) {
          case "user":
            return <UserMessage key={msg.id} message={msg} />;
          case "assistant":
            return <AssistantMessage key={msg.id} message={msg} />;
          case "system":
            return <SystemMessage key={msg.id} message={msg} />;
        }
      })}
      <div ref={bottomRef} />
    </div>
  );
}
