import { useAppState } from "../context/AppStateContext";

export function Footer() {
  const { state } = useAppState();

  const modeLabel = state.mode === "plan" ? "Plan" : "Build";
  const backendLabel = state.backend ?? "default";

  return (
    <div className="footer">
      <span>Multiphysics Modeling Agent</span>
      <div className="footer-right">
        <span className="footer-mode">
          <span className="dot">●</span> {modeLabel}
        </span>
        <span>{backendLabel}</span>
      </div>
    </div>
  );
}
