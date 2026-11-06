/** 尚无 bridge 事件时，仿 DSH「Deep diving…」状态行 */

interface ReasoningLivePlaceholderProps {
  phaseHint: string;
}

export function ReasoningLivePlaceholder({ phaseHint }: ReasoningLivePlaceholderProps) {
  return (
    <div
      className="dsh-process dsh-process--live dsh-process--placeholder"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="dsh-process__status">
        <span className="dsh-process__status-dot" aria-hidden />
        <span className="dsh-process__status-text">深入思考中…</span>
        {phaseHint ? <span className="dsh-process__status-phase">{phaseHint}</span> : null}
      </div>
      <div className="dsh-process-box dsh-process-box--live dsh-process-box--skeleton" aria-hidden>
        <div className="dsh-process-box__items">
          <div className="dsh-skel-line" />
          <div className="dsh-skel-line dsh-skel-line--mid" />
          <div className="dsh-skel-line dsh-skel-line--short" />
        </div>
      </div>
    </div>
  );
}
