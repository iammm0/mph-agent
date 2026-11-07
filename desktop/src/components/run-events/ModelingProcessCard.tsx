import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

interface ProcessStep {
  index?: number;
  action?: string;
  step_type?: string;
  label?: string;
  why?: string;
  inputs?: string[];
  status?: string;
}

export function ModelingProcessCard({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const title = String(d.title ?? "建模细致过程").trim();
  const summary = String(d.summary ?? "").trim();
  const steps = Array.isArray(d.steps) ? (d.steps as ProcessStep[]) : [];

  if (!summary && steps.length === 0) return null;

  return (
    <div className="run-event-card run-event-card--modeling-process">
      <span className="run-event-card__icon" aria-hidden>
        <Icon name="document-code" size={16} />
      </span>
      <div className="run-event-card__main">
        <span className="run-event-card__kicker">建模过程</span>
        <span className="run-event-card__title">{title}</span>
        {summary ? <p className="run-event-card__detail">{summary}</p> : null}
        {steps.length > 0 ? (
          <ol className="modeling-process-list">
            {steps.map((step, i) => {
              const label = step.label || step.action || step.step_type || `步骤 ${i + 1}`;
              const why = String(step.why ?? "").trim();
              const inputs = Array.isArray(step.inputs)
                ? step.inputs.map((x) => String(x ?? "").trim()).filter(Boolean)
                : [];
              const status = String(step.status ?? "").trim();
              return (
                <li key={`${label}-${i}`} className="modeling-process-item">
                  <div className="modeling-process-item__head">
                    <strong>
                      {step.index ?? i + 1}. {label}
                    </strong>
                    {status ? (
                      <span className={`modeling-process-item__status is-${status}`}>
                        {status}
                      </span>
                    ) : null}
                  </div>
                  {why ? <p className="modeling-process-item__why">{why}</p> : null}
                  {inputs.length > 0 ? (
                    <ul className="modeling-process-item__inputs">
                      {inputs.map((input, j) => (
                        <li key={j}>{input}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
    </div>
  );
}
