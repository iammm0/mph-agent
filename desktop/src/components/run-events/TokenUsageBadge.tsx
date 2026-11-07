import type { RunEvent } from "../../lib/types";

function formatNumber(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "-";
  return Math.round(n).toLocaleString("zh-CN");
}

export function TokenUsageBadge({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const prompt = formatNumber(d.prompt_tokens);
  const completion = formatNumber(d.completion_tokens);
  const total = formatNumber(d.total_tokens);
  const source = String(d.source ?? "").trim();
  const cumulative = formatNumber(d.cumulative_total_tokens);

  return (
    <div className="token-usage-badge" title="本次 LLM 调用 token 用量">
      <span className="token-usage-badge__label">tokens</span>
      <span className="token-usage-badge__value">
        in {prompt} · out {completion} · Σ {total}
        {cumulative !== "-" ? ` · 累计 ${cumulative}` : ""}
        {source ? ` · ${source}` : ""}
      </span>
    </div>
  );
}
