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

export function MessageList() {
  const { messages, dispatch } = useAppState();
  const { handleSubmit } = useBridge();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="message-list">
        <div className="message-list-empty">
          <p className="message-list-empty-hint">
            点击下方牛顿环快速案例，系统会切换到执行模式并开始完整仿真建模。
          </p>
          <div className="quick-prompts">
            <p className="quick-prompts-title">快速案例</p>
            {QUICK_PROMPT_GROUPS.map((group: QuickPromptGroup) => (
              <details key={group.title} className="quick-prompts-details" open>
                <summary className="quick-prompts-details-summary">
                  <span className="quick-prompts-details-title">{group.title}</span>
                  {group.hint ? (
                    <span className="quick-prompts-details-hint" title={group.hint}>
                      {group.hint}
                    </span>
                  ) : null}
                </summary>
                <div className="quick-prompts-details-body">
                  <div className="quick-prompts-grid">
                    {group.prompts.map((item: QuickPromptItem) => (
                      <button
                        key={`${group.title}-${item.label}`}
                        type="button"
                        className="quick-prompt-chip"
                        onClick={() => {
                          dispatch({ type: "SET_MODE", mode: "run" });
                          handleSubmit(item.text);
                        }}
                        title={item.text || item.label}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              </details>
            ))}
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
