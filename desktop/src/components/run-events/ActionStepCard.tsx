import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

function getActionIcon(type: string): string {
  if (type === "action_end") return "tick-circle";
  if (type === "exec_result") return "export-circle-01";
  return "play";
}

export function ActionStepCard({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const type = event.type;

  if (type === "action_start") {
    const ui = d.ui as Record<string, unknown> | undefined;
    const thought = d.thought as Record<string, unknown> | undefined;
    const actionText =
      (ui?.action as string | undefined) ??
      (thought ? String(thought.action ?? JSON.stringify(thought)).slice(0, 80) : "");
    const detail = ui?.detail as string | undefined;
    return (
      <div className="run-event-card run-event-card--action">
        <span className="run-event-card__icon run-event-card__icon--play" aria-hidden>
          <Icon name={getActionIcon(type)} size={16} />
        </span>
        <div className="run-event-card__main">
          <span className="run-event-card__title">{actionText || "执行"}</span>
          {detail && <p className="run-event-card__detail">{detail}</p>}
        </div>
      </div>
    );
  }

  if (type === "action_end") {
    const ui = d.ui as Record<string, unknown> | undefined;
    const action = (ui?.action as string | undefined) ?? String(d.action ?? "完成");
    return (
      <div className="run-event-card run-event-card--action-end">
        <span className="run-event-card__icon run-event-card__icon--done" aria-hidden>
          <Icon name="tick-circle" size={16} />
        </span>
        <span className="run-event-card__title">{action}</span>
      </div>
    );
  }

  const result = d.result as Record<string, unknown> | undefined;
  const ui = d.ui as Record<string, unknown> | undefined;
  const status = result?.status as string | undefined;
  const message = result?.message as string | undefined;
  const success = status === "success";
  const title = (ui?.action as string | undefined) ?? message ?? status ?? "执行结果";
  const detail = ui?.detail as string | undefined;
  const target = ui?.target as string | undefined;

  return (
    <div className={`run-event-card run-event-card--result run-event-card--result-${success ? "ok" : "fail"}`}>
      <span className="run-event-card__icon" aria-hidden>
        <Icon name={success ? "tick-circle" : "close-circle"} size={16} />
      </span>
      <div className="run-event-card__main">
        <span className="run-event-card__title">{title}</span>
        {detail && <p className="run-event-card__detail">{detail}</p>}
        {target && <p className="run-event-card__detail run-event-card__detail--secondary">{target}</p>}
      </div>
    </div>
  );
}
