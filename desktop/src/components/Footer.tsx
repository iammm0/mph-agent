import { useAppState } from "../context/AppStateContext";
import { getProviderLabel } from "../lib/apiConfig";
import { AGENT_PHASE_LABELS } from "../lib/types";
import { Icon } from "./Icon";

export function Footer() {
  const { state } = useAppState();

  const phase = AGENT_PHASE_LABELS[state.mode];
  const backendLabel = getProviderLabel(state.backend);

  return (
    <div className="footer">
      <span className="footer-left">
        mph-agent
        <span
          className="footer-workflow-hint"
          title="直接描述需求即可。Agent 会自动探讨、规划；仅在需要澄清时打断，然后执行建模。"
        >
          自动流水线（澄清时打断）
        </span>
      </span>
      <div className="footer-right">
        <span className="footer-mode" title={phase.title}>
          <Icon name={phase.icon} size={13} /> {phase.label}
        </span>
        <span>{backendLabel}</span>
      </div>
    </div>
  );
}
