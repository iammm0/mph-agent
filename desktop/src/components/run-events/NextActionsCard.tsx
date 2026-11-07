import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

export interface NextActionItem {
  id?: string;
  label: string;
  prompt: string;
}

function parseActions(data: Record<string, unknown> | undefined): NextActionItem[] {
  const raw = data?.actions;
  if (!Array.isArray(raw)) return [];
  const actions: NextActionItem[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const label = String(row.label ?? "").trim();
    const prompt = String(row.prompt ?? "").trim();
    if (!label || !prompt) continue;
    actions.push({
      id: String(row.id ?? "").trim() || undefined,
      label,
      prompt,
    });
  }
  return actions;
}

export function extractNextActionsFromEvents(events: RunEvent[] | undefined): {
  title: string;
  hint: string;
  actions: NextActionItem[];
} | null {
  if (!events?.length) return null;
  for (let i = events.length - 1; i >= 0; i--) {
    const evt = events[i];
    if (evt?.type !== "next_actions") continue;
    const actions = parseActions(evt.data);
    if (!actions.length) return null;
    return {
      title: String(evt.data?.title ?? "下一步可执行建议"),
      hint: String(evt.data?.hint ?? "点击即可作为提示词发送"),
      actions,
    };
  }
  return null;
}

export function NextActionsCard({
  event,
  title,
  hint,
  actions,
  disabled,
  onSend,
}: {
  event?: RunEvent;
  title?: string;
  hint?: string;
  actions?: NextActionItem[];
  disabled?: boolean;
  onSend: (prompt: string) => void;
}) {
  const fromEvent = event ? parseActions(event.data) : [];
  const list = actions?.length ? actions : fromEvent;
  const heading = title || String(event?.data?.title ?? "下一步可执行建议");
  const sub = hint || String(event?.data?.hint ?? "点击即可作为提示词发送");
  if (!list.length) return null;

  return (
    <div className="next-actions-card">
      <div className="next-actions-card__head">
        <span className="next-actions-card__icon" aria-hidden>
          <Icon name="flash" size={15} />
        </span>
        <div>
          <div className="next-actions-card__title">{heading}</div>
          <div className="next-actions-card__hint">{sub}</div>
        </div>
      </div>
      <div className="next-actions-card__chips">
        {list.map((action) => (
          <button
            key={action.id || action.label}
            type="button"
            className="next-actions-chip"
            disabled={disabled}
            title={action.prompt}
            onClick={() => onSend(action.prompt)}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
