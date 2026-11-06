import { useAppState } from "../../context/AppStateContext";
import {
  getProviderLabel,
  saveApiConfig,
  loadApiConfig,
} from "../../lib/apiConfig";

export function BackendDialog({ onClose }: { onClose: () => void }) {
  const { dispatch, addMessage, state } = useAppState();

  const selectDeepSeek = () => {
    dispatch({ type: "SET_BACKEND", backend: "deepseek" });
    saveApiConfig({ ...loadApiConfig(), preferred_backend: "deepseek" });
    addMessage("system", "已选择后端: " + getProviderLabel("deepseek"));
    onClose();
  };

  return (
    <>
      <div className="dialog-header">模型后端</div>
      <div className="dialog-body">
        <div className="dialog-option" onClick={selectDeepSeek}>
          <span className="dialog-option-name">
            DeepSeek
            {state.backend === "deepseek" || !state.backend ? "（当前）" : ""}
          </span>
          <span className="dialog-option-desc">DeepSeek 官方接口</span>
        </div>
      </div>
    </>
  );
}
