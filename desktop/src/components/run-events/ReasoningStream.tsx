import { useEffect, useMemo, useState } from "react";
import type { RunEvent } from "../../lib/types";
import { RunEventBlock } from "./index";
import { Icon } from "../Icon";

const PHASE_LABELS: Record<string, string> = {
  planning: "规划",
  scanning_capabilities: "扫描能力",
  thinking: "思考",
  planning_steps: "排布步骤",
  executing: "执行",
  observing: "观察",
  iterating: "根据结果调整",
  qa: "问答",
  discussion: "探讨",
  plan_confirmed: "计划确认",
};

type TokenBudgetPayload = {
  phase?: string;
  model?: string;
  prompt_tokens?: unknown;
  soft_input_limit_tokens?: unknown;
  hard_input_limit_tokens?: unknown;
  exceeds_soft_limit?: unknown;
  exceeds_hard_limit?: unknown;
  tokenizer_backend?: unknown;
  tokenizer_accurate?: unknown;
  report?: unknown;
};

type PlanRuntimeSyncPayload = {
  phase?: string;
  after_count?: unknown;
  synced_tasks?: unknown;
  store_path?: unknown;
  sha256?: unknown;
  error?: unknown;
};

/** 合并连续的 llm_stream_chunk 为单条 */
function mergeStreamChunks(events: RunEvent[]): RunEvent[] {
  const out: RunEvent[] = [];
  let buf = "";
  let phase = "";
  for (const e of events) {
    if (e.type === "llm_stream_chunk") {
      buf += (e.data?.chunk ?? e.data?.text ?? "") as string;
      phase = (e.data?.phase ?? phase) as string;
      continue;
    }
    if (buf) {
      out.push({ _event: true, type: "llm_stream_chunk", data: { phase, chunk: buf, text: buf } });
      buf = "";
    }
    out.push(e);
  }
  if (buf) out.push({ _event: true, type: "llm_stream_chunk", data: { phase, chunk: buf, text: buf } });
  return out;
}

const CAPABILITY_SCAN_TYPES = new Set([
  "capability_scan_start",
  "capability_scan_progress",
  "capability_scan_hit",
  "capability_scan_end",
]);

/** 把同一阶段块内连续的 capability_scan_* 折叠为一个虚拟事件，由 CapabilityScanCard 统一渲染 */
function mergeCapabilityScan(events: RunEvent[]): RunEvent[] {
  const out: RunEvent[] = [];
  let buffer: RunEvent[] = [];
  const flush = () => {
    if (buffer.length === 0) return;
    out.push({
      _event: true,
      type: "capability_scan",
      data: { events: buffer },
    });
    buffer = [];
  };
  for (const evt of events) {
    if (CAPABILITY_SCAN_TYPES.has(evt.type)) {
      buffer.push(evt);
      continue;
    }
    flush();
    out.push(evt);
  }
  flush();
  return out;
}

function lastEventOfType(events: RunEvent[], type: string): RunEvent | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i]?.type === type) return events[i];
  }
  return null;
}

function formatNumber(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "";
  return n.toLocaleString();
}

function BudgetBadge({ event }: { event: RunEvent }) {
  const d = (event.data ?? {}) as TokenBudgetPayload;
  const exceedsHard = Boolean(d.exceeds_hard_limit);
  const exceedsSoft = Boolean(d.exceeds_soft_limit);
  const severity = exceedsHard ? "hard" : exceedsSoft ? "soft" : "ok";
  const promptTokens = formatNumber(d.prompt_tokens);
  const soft = formatNumber(d.soft_input_limit_tokens);
  const model = String(d.model ?? "").trim();
  const report = String(d.report ?? "").trim();

  return (
    <details className={`reasoning-badge reasoning-badge--budget reasoning-badge--${severity}`}>
      <summary className="reasoning-badge__summary" title="Token 预算（点击展开）">
        <span className="reasoning-badge__label">tokens</span>
        <span className="reasoning-badge__value">
          {promptTokens || "-"}
          {soft ? ` / ${soft}` : ""}
        </span>
        {model ? <span className="reasoning-badge__meta">{model}</span> : null}
      </summary>
      {report ? <pre className="reasoning-badge__detail">{report}</pre> : null}
    </details>
  );
}

function PlanSyncBadge({ event }: { event: RunEvent }) {
  const d = (event.data ?? {}) as PlanRuntimeSyncPayload;
  const error = String(d.error ?? "").trim();
  const severity = error ? "fail" : "ok";
  const steps = formatNumber(d.after_count);
  const tasks = formatNumber(d.synced_tasks);
  const storePath = String(d.store_path ?? "").trim();
  const sha = String(d.sha256 ?? "").trim();

  return (
    <details className={`reasoning-badge reasoning-badge--plan reasoning-badge--${severity}`}>
      <summary className="reasoning-badge__summary" title="计划镜像状态（点击展开）">
        <span className="reasoning-badge__label">plan</span>
        <span className="reasoning-badge__value">
          {steps ? `steps=${steps}` : "steps=-"}
          {tasks ? ` · tasks=${tasks}` : ""}
        </span>
      </summary>
      <pre className="reasoning-badge__detail">
        {JSON.stringify(
          {
            store_path: storePath || undefined,
            sha256: sha || undefined,
            error: error || undefined,
          },
          null,
          2
        )}
      </pre>
    </details>
  );
}

export interface PhaseBlock {
  phase: string;
  label: string;
  events: RunEvent[];
  isCurrent: boolean;
}

/** 按 task_phase 将事件分成多个阶段块，便于按「阶段 + 思考」展示 */
export function groupEventsByPhase(events: RunEvent[]): PhaseBlock[] {
  const merged = mergeStreamChunks(events);
  const blocks: PhaseBlock[] = [];
  let current: RunEvent[] = [];
  let currentPhase = "";
  let currentLabel = "规划";

  for (const e of merged) {
    if (e.type === "task_phase" && e.data?.phase) {
      if (current.length > 0) {
        blocks.push({
          phase: currentPhase,
          label: PHASE_LABELS[currentPhase] ?? (currentPhase || "规划"),
          events: current,
          isCurrent: false,
        });
        current = [];
      }
      currentPhase = e.data.phase as string;
      currentLabel = PHASE_LABELS[currentPhase] ?? currentPhase;
      continue;
    }
    if (e.type === "plan_start") {
      if (current.length > 0) {
        blocks.push({ phase: currentPhase, label: currentLabel, events: current, isCurrent: false });
        current = [];
      }
      currentPhase = "planning";
      currentLabel = "规划";
    }
    current.push(e);
  }

  if (current.length > 0 || currentPhase) {
    blocks.push({
      phase: currentPhase,
      label: currentLabel,
      events: current,
      isCurrent: true,
    });
  } else if (blocks.length > 0) {
    blocks[blocks.length - 1].isCurrent = true;
  }

  return blocks;
}

function visiblePhaseEvents(events: RunEvent[]): RunEvent[] {
  const filtered = events.filter(
    (evt) => evt.type !== "token_budget" && evt.type !== "plan_runtime_sync"
  );
  return mergeCapabilityScan(filtered);
}

function buildPhaseSummary(block: PhaseBlock): string {
  const last = (() => {
    for (let i = block.events.length - 1; i >= 0; i--) {
      const e = block.events[i];
      if (e.type === "llm_stream_chunk") {
        const text = String(e.data?.chunk ?? e.data?.text ?? "").trim();
        if (text) return text;
      }
    }
    return "";
  })();
  if (last) {
    const collapsed = last.replace(/\s+/g, " ");
    return collapsed.length > 60 ? `${collapsed.slice(0, 60)}…` : collapsed;
  }
  const evtCount = block.events.filter(
    (e) => e.type !== "token_budget" && e.type !== "plan_runtime_sync"
  ).length;
  return evtCount > 0 ? `${evtCount} 条事件` : "已完成";
}

interface PhaseSectionProps {
  block: PhaseBlock;
  isLive: boolean;
}

function PhaseSection({ block, isLive }: PhaseSectionProps) {
  const visible = useMemo(() => visiblePhaseEvents(block.events), [block.events]);
  const summary = useMemo(() => buildPhaseSummary(block), [block]);

  // 默认展开当前阶段；非 current 阶段默认收起。
  // 用户手动 toggle 后锁定状态，不再被 isCurrent 切换覆盖。
  const [expanded, setExpanded] = useState<boolean>(block.isCurrent);
  const [userTouched, setUserTouched] = useState<boolean>(false);

  useEffect(() => {
    if (userTouched) return;
    setExpanded(block.isCurrent);
  }, [block.isCurrent, userTouched]);

  const handleToggle = () => {
    setUserTouched(true);
    setExpanded((v) => !v);
  };

  let lastStreamIndex = -1;
  if (isLive && block.isCurrent && expanded) {
    visible.forEach((evt, idx) => {
      if (evt.type === "llm_stream_chunk") lastStreamIndex = idx;
    });
  }

  const budget = lastEventOfType(block.events, "token_budget");
  const sync = lastEventOfType(block.events, "plan_runtime_sync");
  const collapsible = !block.isCurrent;

  return (
    <section
      className={`reasoning-stream__phase ${block.isCurrent ? "reasoning-stream__phase--current" : ""}${isLive && block.isCurrent ? " reasoning-stream__phase--pulsing" : ""}${expanded ? " reasoning-stream__phase--expanded" : " reasoning-stream__phase--collapsed"}`}
      data-phase={block.phase}
      data-collapsible={collapsible ? "true" : "false"}
    >
      <div className="reasoning-stream__phase-header">
        <div className="reasoning-stream__phase-title-row">
          {collapsible ? (
            <button
              type="button"
              className="reasoning-stream__phase-toggle"
              onClick={handleToggle}
              aria-expanded={expanded}
              title={expanded ? "收起本阶段" : "展开本阶段"}
            >
              <span className="reasoning-stream__phase-toggle-arrow" aria-hidden>
                <Icon name={expanded ? "arrow-down-01" : "arrow-right-01"} size={14} />
              </span>
              <span className="reasoning-stream__phase-label">{block.label}</span>
            </button>
          ) : (
            <span className="reasoning-stream__phase-label">{block.label}</span>
          )}
          {isLive && block.isCurrent && (
            <span className="reasoning-stream__live-chip" title="正在输出">
              <span className="reasoning-stream__live-chip-dot" aria-hidden />
              LIVE
            </span>
          )}
          {!expanded && summary ? (
            <span className="reasoning-stream__phase-summary" title={summary}>
              {summary}
            </span>
          ) : null}
        </div>
        <div className="reasoning-stream__phase-badges">
          {budget ? <BudgetBadge event={budget} /> : null}
          {sync ? <PlanSyncBadge event={sync} /> : null}
        </div>
      </div>
      {expanded ? (
        <div className="reasoning-stream__phase-events">
          {visible.map((evt, j) => (
            <RunEventBlock
              key={j}
              event={evt}
              isLiveStreamTail={lastStreamIndex === j}
              isLive={isLive && block.isCurrent}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** 按阶段渲染流式思考与执行结果，突出每个阶段在做什么 */
export function ReasoningStream({
  events,
  isLive = false,
}: {
  events: RunEvent[];
  /** 当前助手消息对应会话仍在执行：启用阶段动效与流式尾光标 */
  isLive?: boolean;
}) {
  const blocks = groupEventsByPhase(events);
  if (blocks.length === 0) return null;

  return (
    <div className={`reasoning-stream${isLive ? " reasoning-stream--live" : ""}`}>
      {blocks.map((block, i) => (
        <PhaseSection key={`${block.phase}-${i}`} block={block} isLive={isLive} />
      ))}
    </div>
  );
}
