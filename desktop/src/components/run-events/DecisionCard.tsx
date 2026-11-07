import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

const KIND_META: Record<string, { label: string; icon: string }> = {
  plan_rationale: { label: "推理思路", icon: "message-question" },
  step_decision: { label: "步骤决策", icon: "task-square" },
  adjust_decision: { label: "调整决策", icon: "flash" },
};

export function DecisionCard({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const kind = String(d.kind ?? "step_decision");
  const meta = KIND_META[kind] ?? { label: "决策依据", icon: "info-circle" };
  const title = String(d.title ?? meta.label).trim();
  const reasoning = String(d.reasoning ?? "").trim();
  const basis = String(d.basis ?? "").trim();
  const progress = String(d.progress ?? "").trim();
  const inputs = Array.isArray(d.inputs)
    ? d.inputs.map((item) => String(item ?? "").trim()).filter(Boolean)
    : [];

  if (!reasoning && !basis && inputs.length === 0) return null;

  return (
    <div className={`run-event-card run-event-card--decision run-event-card--decision-${kind}`}>
      <span className="run-event-card__icon" aria-hidden>
        <Icon name={meta.icon} size={16} />
      </span>
      <div className="run-event-card__main">
        <div className="run-event-card__title-row">
          <span className="run-event-card__kicker">{meta.label}</span>
          {progress ? <span className="run-event-card__progress">{progress}</span> : null}
        </div>
        <span className="run-event-card__title">{title}</span>
        {reasoning ? <p className="run-event-card__detail run-event-card__reasoning">{reasoning}</p> : null}
        {basis ? (
          <div className="run-event-card__basis">
            <span className="run-event-card__basis-label">决策依据</span>
            <p className="run-event-card__basis-text">{basis}</p>
          </div>
        ) : null}
        {inputs.length > 0 ? (
          <ul className="run-event-card__list run-event-card__inputs">
            {inputs.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
