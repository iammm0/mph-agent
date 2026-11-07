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
              在左侧新建工作空间后，可在同一目录下开多个 Agent 任务。各任务产物在 context/models/plans/tasks/&lt;任务id&gt;/。
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
