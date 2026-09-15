import { useMemo, useState } from "react";
import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

function safeString(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatNumber(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "";
  return n.toLocaleString();
}

export function PlanRuntimeSyncCard({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const phase = String(d.phase ?? "").trim();
  const after = formatNumber(d.after_count);
  const synced = formatNumber(d.synced_tasks);
  const storePath = String(d.store_path ?? "").trim();
  const sha = String(d.sha256 ?? "").trim();
  const error = String(d.error ?? "").trim();

  const [expanded, setExpanded] = useState(false);

  const severity = useMemo(() => (error ? "fail" : "ok"), [error]);
  const title = useMemo(
    () => (error ? "计划镜像同步失败" : "计划镜像已同步"),
    [error]
  );

  return (
    <div className={`run-event-card run-event-card--plan-sync run-event-card--plan-sync-${severity}`}>
      <span className="run-event-card__icon" aria-hidden>
        <Icon name={error ? "close-circle" : "clipboard-tick"} size={16} />
      </span>
      <div className="run-event-card__main">
        <div className="run-event-card__row">
          <span className="run-event-card__title">{title}</span>
          <button
            type="button"
            className="run-event-card__toggle"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "收起" : "详情"}
          </button>
        </div>
        <p className="run-event-card__detail">{phase ? `阶段：${phase}` : "阶段：-"}</p>
        <p className="run-event-card__detail run-event-card__detail--secondary">
          steps={after || "-"} · tasks={synced || "-"}
        </p>
        {expanded && (
          <pre className="run-event-card__pre">
            {safeString({
              store_path: storePath || undefined,
              sha256: sha || undefined,
              error: error || undefined,
            })}
          </pre>
        )}
      </div>
    </div>
  );
}

