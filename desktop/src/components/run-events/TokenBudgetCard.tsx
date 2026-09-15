import { useMemo, useState } from "react";
import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

function formatNumber(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "";
  return n.toLocaleString();
}

export function TokenBudgetCard({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const phase = String(d.phase ?? "").trim();
  const model = String(d.model ?? "").trim();
  const promptTokens = formatNumber(d.prompt_tokens);
  const soft = formatNumber(d.soft_input_limit_tokens);
  const hard = formatNumber(d.hard_input_limit_tokens);
  const exceedsHard = Boolean(d.exceeds_hard_limit);
  const exceedsSoft = Boolean(d.exceeds_soft_limit);
  const tokenizer = String(d.tokenizer_backend ?? "").trim();
  const accurate = d.tokenizer_accurate === true;
  const report = String(d.report ?? "").trim();

  const [expanded, setExpanded] = useState(false);

  const severity = useMemo(() => {
    if (exceedsHard) return "hard";
    if (exceedsSoft) return "soft";
    return "ok";
  }, [exceedsHard, exceedsSoft]);

  const headline = useMemo(() => {
    if (severity === "hard") return "Token 预算超限（硬限制）";
    if (severity === "soft") return "Token 预算紧张（软限制）";
    return "Token 预算";
  }, [severity]);

  return (
    <div className={`run-event-card run-event-card--budget run-event-card--budget-${severity}`}>
      <span className="run-event-card__icon" aria-hidden>
        <Icon name="chart" size={16} />
      </span>
      <div className="run-event-card__main">
        <div className="run-event-card__row">
          <span className="run-event-card__title">{headline}</span>
          <button
            type="button"
            className="run-event-card__toggle"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "收起" : "详情"}
          </button>
        </div>
        <p className="run-event-card__detail">
          {phase ? `阶段：${phase}` : "阶段：-"}
          {model ? ` · 模型：${model}` : ""}
        </p>
        <p className="run-event-card__detail run-event-card__detail--secondary">
          prompt={promptTokens || "-"} · soft={soft || "-"} · hard={hard || "-"} · tokenizer=
          {tokenizer || "-"}
          {tokenizer ? (accurate ? " (accurate)" : " (fallback)") : ""}
        </p>
        {expanded && report && <pre className="run-event-card__pre">{report}</pre>}
      </div>
    </div>
  );
}

