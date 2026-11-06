import { MessageList } from "./MessageList";
import { Prompt } from "./Prompt";
import { useAppState } from "../context/AppStateContext";

export function Session() {
  const { state } = useAppState();
  const hasWorkspace = Boolean(state.currentConversationId && state.workspaceDir);

  return (
    <div className="session-layout">
      <div className="session-main">
        {hasWorkspace ? (
          <>
            <MessageList />
            <Prompt />
          </>
        ) : (
          <div className="session-empty-workspace">
            <h2>创建工作空间开始建模</h2>
            <p>
              在左侧选择本地目录新建工作空间。对话记录会写入 context/，计划写入 plans/，模型写入 models/。
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
