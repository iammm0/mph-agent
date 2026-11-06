import { useEffect, useMemo, useState } from "react";
import type { RunEvent } from "../../lib/types";
import { RunEventBlock } from "./index";
import { Icon } from "../Icon";
import { sanitizeLLMDisplayText } from "../../lib/textSanitizer";

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

/** 进行中状态文案（仿 DSH “Deep diving…”） */
const LIVE_STATUS: Record<string, string> = {
  planning: "规划中…",
  scanning_capabilities: "扫描能力中…",
  thinking: "深入思考中…",
  planning_steps: "排布步骤中…",
  executing: "执行中…",
  observing: "观察结果中…",
  iterating: "根据结果调整中…",
  qa: "问答中…",
  discussion: "探讨中…",
  plan_confirmed: "确认计划中…",
};

const TOOLISH_TYPES = new Set([
  "action_start",
  "action_end",
  "exec_result",
  "step_start",
  "step_end",
  "material_start",
  "material_end",
  "capability_scan",
  "geometry_3d",
  "coupling_added",
]);

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

/** 把同一阶段块内连续的 capability_scan_* 折叠为一个虚拟事件 */
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
      <summary className="reasoning-badge__summary" title="Token 预算">
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
      <summary className="reasoning-badge__summary" title="计划镜像状态">
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

/** 按 task_phase 将事件分成多个阶段块 */
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

function countToolCalls(events: RunEvent[]): number {
  return events.filter((e) => TOOLISH_TYPES.has(e.type)).length;
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(sec < 10 ? 1 : 0)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function eventOneLine(event: RunEvent): string {
  const d = event.data ?? {};
  switch (event.type) {
    case "llm_stream_chunk":
    case "think_chunk": {
      const text = sanitizeLLMDisplayText(
        String(d.chunk ?? d.text ?? (d.thought as { reasoning?: string } | undefined)?.reasoning ?? "")
      ).replace(/\s+/g, " ").trim();
      return text.length > 72 ? `${text.slice(0, 72)}…` : text || "思考";
    }
    case "action_start": {
      const ui = d.ui as Record<string, unknown> | undefined;
      const thought = d.thought as Record<string, unknown> | undefined;
      return String(ui?.action ?? thought?.action ?? "执行").slice(0, 80);
    }
    case "action_end": {
      const ui = d.ui as Record<string, unknown> | undefined;
      return String(ui?.action ?? d.action ?? "完成");
    }
    case "exec_result": {
      const ui = d.ui as Record<string, unknown> | undefined;
      const result = d.result as Record<string, unknown> | undefined;
      return String(ui?.action ?? result?.message ?? result?.status ?? "执行结果");
    }
    case "plan_start":
      return "规划开始";
    case "plan_end":
      return "规划完成";
    case "step_start":
    case "step_end":
      return String(d.message ?? (event.type === "step_end" ? "步骤完成" : "步骤开始"));
    case "material_start":
      return String(d.message ?? "设置材料");
    case "material_end":
      return "材料设置完成";
    case "capability_scan":
      return "能力扫描";
    case "observation":
      return String(d.message ?? "观察").slice(0, 80);
    case "error":
      return String(d.message ?? "错误").slice(0, 80);
    case "content":
      return String(d.content ?? d.text ?? "内容").slice(0, 80);
    default:
      return event.type;
  }
}

function isThinkEvent(type: string): boolean {
  return type === "llm_stream_chunk" || type === "think_chunk";
}

function isToolEvent(type: string): boolean {
  return TOOLISH_TYPES.has(type);
}

/** 折叠时每个过程框默认露出的最新条目数（对齐 dsh-process-fold） */
const COLLAPSED_VISIBLE = 2;

interface ProcessBoxProps {
  block: PhaseBlock;
  isLive: boolean;
  turnExpanded: boolean;
}

function ProcessBox({ block, isLive, turnExpanded }: ProcessBoxProps) {
  const visible = useMemo(() => visiblePhaseEvents(block.events), [block.events]);
  /** 堆叠线单独展开本框；整轮收起时清掉 */
  const [boxSoloOpen, setBoxSoloOpen] = useState(false);

  // 进行中始终展开；整轮开关打开则全开；堆叠线可单独打开某一框
  const forceOpen = isLive && block.isCurrent;
  const expanded = forceOpen || turnExpanded || boxSoloOpen;

  useEffect(() => {
    if (!turnExpanded && !forceOpen) setBoxSoloOpen(false);
  }, [turnExpanded, forceOpen]);

  const hiddenCount = expanded ? 0 : Math.max(0, visible.length - COLLAPSED_VISIBLE);
  const shown = expanded ? visible : visible.slice(-COLLAPSED_VISIBLE);

  let lastStreamIndex = -1;
  if (isLive && block.isCurrent && expanded) {
    shown.forEach((evt, idx) => {
      if (evt.type === "llm_stream_chunk") lastStreamIndex = idx;
    });
  }

  const budget = lastEventOfType(block.events, "token_budget");
  const sync = lastEventOfType(block.events, "plan_runtime_sync");

  const openBox = () => setBoxSoloOpen(true);
  const closeBox = () => setBoxSoloOpen(false);

  if (visible.length === 0 && !budget && !sync) return null;

  return (
    <div
      className={[
        "dsh-process-box",
        expanded ? "dsh-process-box--open" : "dsh-process-box--collapsed",
        hiddenCount > 0 ? "dsh-process-box--has-more" : "",
        block.isCurrent ? "dsh-process-box--current" : "",
        forceOpen ? "dsh-process-box--live" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-phase={block.phase}
    >
      {hiddenCount > 0 && (
        <button
          type="button"
          className="dsh-process-box__stack"
          onClick={openBox}
          title={`展开本框（另有 ${hiddenCount} 项）`}
          aria-label={`展开过程框，另有 ${hiddenCount} 项`}
        >
          <span className="dsh-process-box__stack-line" aria-hidden />
          <span className="dsh-process-box__stack-line" aria-hidden />
        </button>
      )}

      {expanded && !forceOpen && (
        <button
          type="button"
          className="dsh-process-box__collapse-edge"
          onClick={closeBox}
          title="收起本框"
          aria-label="收起过程框"
        >
          <span className="dsh-process-box__collapse-icon" aria-hidden>
            <span className="dsh-process-box__stack-line" />
            <span className="dsh-process-box__stack-line" />
          </span>
        </button>
      )}

      <div className="dsh-process-box__header">
        <span className="dsh-process-box__phase">{block.label}</span>
        {(budget || sync) && (
          <div className="dsh-process-box__badges">
            {budget ? <BudgetBadge event={budget} /> : null}
            {sync ? <PlanSyncBadge event={sync} /> : null}
          </div>
        )}
      </div>

      <div className="dsh-process-box__items">
        {shown.map((evt, j) => (
          <ProcessItem
            key={j}
            event={evt}
            isLiveStreamTail={lastStreamIndex === j}
            isLive={isLive && block.isCurrent}
            compact={!expanded && isThinkEvent(evt.type)}
          />
        ))}
      </div>
    </div>
  );
}

function ProcessItem({
  event,
  isLiveStreamTail,
  isLive,
  compact,
}: {
  event: RunEvent;
  isLiveStreamTail?: boolean;
  isLive?: boolean;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(() => isThinkEvent(event.type) && Boolean(isLive));
  const type = event.type ?? "";
  const line = eventOneLine(event);
  const think = isThinkEvent(type);
  const tool = isToolEvent(type);

  // 思考行：默认折叠为一行预览（仿 DSH ReasoningRow）；进行中展开
  if (think) {
    const full = sanitizeLLMDisplayText(
      String(event.data?.chunk ?? event.data?.text ?? "")
    );
    const preview = line;
    const showBody = open || Boolean(isLiveStreamTail);

    return (
      <div
        className={`dsh-process-item dsh-process-item--think${showBody ? " is-open" : ""}${
          isLiveStreamTail ? " is-streaming" : ""
        }`}
      >
        <button
          type="button"
          className="dsh-process-item__head"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={showBody}
        >
          <span className="dsh-process-item__kind">思考</span>
          {!showBody && preview ? (
            <span className="dsh-process-item__preview" title={preview}>
              {preview}
            </span>
          ) : (
            <span className="dsh-process-item__hint">
              {isLiveStreamTail ? "输出中" : "已折叠"}
            </span>
          )}
          <span className="dsh-process-item__chevron" aria-hidden>
            <Icon name={showBody ? "arrow-down-01" : "arrow-right-01"} size={12} />
          </span>
        </button>
        {showBody && (
          <div
            className={`dsh-process-item__body${
              isLiveStreamTail ? " dsh-process-item__body--live" : ""
            }`}
          >
            {full || (isLiveStreamTail ? "" : preview)}
            {isLiveStreamTail && <span className="dsh-process-item__caret" aria-hidden />}
          </div>
        )}
      </div>
    );
  }

  if (compact) {
    return (
      <div className="dsh-process-item dsh-process-item--compact">
        <span className="dsh-process-item__kind">{tool ? "工具" : "步骤"}</span>
        <span className="dsh-process-item__preview">{line}</span>
      </div>
    );
  }

  // 工具 / 动作：紧凑头行 + 可展开详情（仿 DSH tool disclosure）
  if (tool || type === "plan_start" || type === "plan_end" || type === "observation" || type === "error") {
    return (
      <details
        className={`dsh-process-item dsh-process-item--tool${
          type === "error" ? " dsh-process-item--error" : ""
        }${type === "observation" ? " dsh-process-item--obs" : ""}`}
      >
        <summary className="dsh-process-item__head">
          <span className="dsh-process-item__kind">
            {type === "error" ? "错误" : type === "observation" ? "观察" : tool ? "工具" : "步骤"}
          </span>
          <span className="dsh-process-item__preview" title={line}>
            {line}
          </span>
        </summary>
        <div className="dsh-process-item__detail">
          <RunEventBlock event={event} isLive={isLive} />
        </div>
      </details>
    );
  }

  return (
    <div className="dsh-process-item dsh-process-item--block">
      <RunEventBlock event={event} isLiveStreamTail={isLiveStreamTail} isLive={isLive} />
    </div>
  );
}

/** 仿 DeepSeek Harness：过程框折叠 +「N 次工具调用」整轮开关 */
export function ReasoningStream({
  events,
  isLive = false,
  startedAt,
  finishedAt,
}: {
  events: RunEvent[];
  /** 当前助手消息对应会话仍在执行 */
  isLive?: boolean;
  startedAt?: number;
  finishedAt?: number;
}) {
  const blocks = groupEventsByPhase(events);
  const allVisible = useMemo(
    () => blocks.flatMap((b) => visiblePhaseEvents(b.events)),
    [blocks]
  );
  const toolCount = useMemo(() => countToolCalls(allVisible), [allVisible]);
  const thinkCount = useMemo(
    () => allVisible.filter((e) => isThinkEvent(e.type)).length,
    [allVisible]
  );

  // 进行中默认展开；结束后默认收起（对齐 DSH 标准/详细模式）
  const [turnExpanded, setTurnExpanded] = useState(isLive);
  const [userTouched, setUserTouched] = useState(false);

  useEffect(() => {
    if (userTouched) return;
    setTurnExpanded(isLive);
  }, [isLive, userTouched]);

  const currentPhase = blocks.find((b) => b.isCurrent)?.phase ?? "";
  const liveLabel = LIVE_STATUS[currentPhase] ?? "深入思考中…";

  const durationMs =
    !isLive && startedAt
      ? (finishedAt ?? Date.now()) - startedAt
      : null;
  const tookLabel = durationMs != null ? formatDuration(durationMs) : "";

  const toggleLabel =
    toolCount > 0
      ? `${toolCount} 次工具调用`
      : thinkCount > 0
        ? `${thinkCount} 步思考`
        : `${allVisible.length} 项过程`;

  if (blocks.length === 0) return null;

  return (
    <div className={`dsh-process${isLive ? " dsh-process--live" : ""}`}>
      {isLive && (
        <div className="dsh-process__status" role="status" aria-live="polite">
          <span className="dsh-process__status-dot" aria-hidden />
          <span className="dsh-process__status-text">{liveLabel}</span>
        </div>
      )}

      <div className="dsh-process__boxes">
        {blocks.map((block, i) => (
          <ProcessBox
            key={`${block.phase}-${i}`}
            block={block}
            isLive={isLive}
            turnExpanded={turnExpanded}
          />
        ))}
      </div>

      {!isLive && (
        <button
          type="button"
          className={`dsh-process__toggle${turnExpanded ? " is-open" : ""}`}
          onClick={() => {
            setUserTouched(true);
            setTurnExpanded((v) => !v);
          }}
          aria-expanded={turnExpanded}
        >
          <span className="dsh-process__toggle-label">{toggleLabel}</span>
          {tookLabel ? <span className="dsh-process__toggle-took">用时 {tookLabel}</span> : null}
          <span className="dsh-process__toggle-chevron" aria-hidden>
            <Icon name="arrow-down-01" size={14} />
          </span>
        </button>
      )}
    </div>
  );
}
