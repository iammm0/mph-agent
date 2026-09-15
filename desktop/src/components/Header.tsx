import { useAppState } from "../context/AppStateContext";
import { Icon } from "./Icon";

export function Header() {
  const { dispatch, sessionTitle, messages } = useAppState();

  return (
    <div className="header">
      <span className="header-title"># {sessionTitle}</span>
      <div className="header-right">
        <span className="header-badge">{messages.length} 条消息</span>
        <button
          type="button"
          className="header-settings-btn"
          onClick={() => dispatch({ type: "SET_VIEW", view: "settings" })}
          title="设置"
          aria-label="设置"
        >
          <Icon name="setting-2" size={16} />
        </button>
      </div>
    </div>
  );
}
