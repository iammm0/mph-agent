import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

export function MaterialCard({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const type = event.type;

  if (type === "material_start") {
    const msg = String(d.message ?? "添加材料...").trim();
    return (
      <div className="run-event-card run-event-card--material">
        <span className="run-event-card__icon" aria-hidden>
          <Icon name="layer" size={16} />
        </span>
        <span className="run-event-card__title">{msg}</span>
      </div>
    );
  }

  const mats = d.materials as Array<{ material?: string; label?: string }> | undefined;
  return (
    <div className="run-event-card run-event-card--material-end">
      <span className="run-event-card__icon" aria-hidden>
        <Icon name="tick-circle" size={16} />
      </span>
      <div className="run-event-card__main">
        <span className="run-event-card__title">材料设置完成</span>
        {mats?.length ? (
          <ul className="run-event-card__list">
            {mats.map((m, i) => (
              <li key={i}>{m.label || m.material || `材料 ${i + 1}`}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
