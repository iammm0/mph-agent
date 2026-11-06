import { MessageList } from "./MessageList";
import { Prompt } from "./Prompt";

export function Session() {
  return (
    <div className="session-layout">
      <div className="session-main">
        <MessageList />
        <Prompt />
      </div>
    </div>
  );
}
