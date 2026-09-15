import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

export function ErrorAlert({ event }: { event: RunEvent }) {
  const message = String(event.data?.message ?? "").trim();
  if (!message) return null;

  return (
    <div className="run-event-alert run-event-alert--error">
      <span className="run-event-alert__icon" aria-hidden>
        <Icon name="close-circle" size={16} />
      </span>
      <p className="run-event-alert__text">{message}</p>
    </div>
  );
}