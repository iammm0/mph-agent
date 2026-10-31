import { MessageList } from "./MessageList";
import { Prompt } from "./Prompt";
import { Icon } from "./Icon";
import { useAppState } from "../context/AppStateContext";

/** Claude 式会话头部：会话标题 + 新对话入口 */
function SessionHeader() {
  const { dispatch, sessionTitle, messages } = useAppState();
  return (
    <div className="session-header">
      <span className="session-header-title" title={sessionTitle || undefined}>
        {sessionTitle || "新对话"}
      </span>
      <div className="session-header-actions">
        <span className="titlebar-badge" title="当前会话消息数">
          {messages.length} 条消息
        </span>
        <button
          type="button"
          className="session-header-btn primary"
          onClick={() => dispatch({ type: "NEW_CONVERSATION" })}
          title="新建对话"
        >
          <Icon name="add" size={13} />
          新对话
        </button>
      </div>
    </div>
  );
}

export function Session() {
  return (
    <div className="session-layout">
      <div className="session-main">
        <SessionHeader />
        <MessageList />
        <Prompt />
      </div>
    </div>
  );
}
