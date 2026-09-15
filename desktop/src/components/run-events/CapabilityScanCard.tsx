import { useEffect, useMemo, useRef, useState } from "react";
import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";

type ScanHit = {
  name: string;
  title?: string;
  score?: number;
  matchedTerms?: string[];
  category?: string;
  invokeMode?: string;
};

type ScanState = {
  query: string;
  total: number;
  scanned: number;
  topK: number;
  mode: string;
  currentNames: string[];
  hits: Map<string, ScanHit>;
  finalHits: ScanHit[];
  finished: boolean;
  elapsedMs: number;
};

const COLLAPSE_DELAY_MS = 600;

function num(value: unknown, fallback = 0): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function strArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => str(v)).filter((v) => v.length > 0);
}

function pickHitFromPayload(d: Record<string, unknown>): ScanHit {
  return {
    name: str(d.name),
    title: str(d.title) || undefined,
    score: typeof d.score === "number" ? d.score : Number(d.score) || undefined,
    matchedTerms: strArray(d.matched_terms),
    category: str(d.category) || undefined,
    invokeMode: str(d.invoke_mode) || undefined,
  };
}

function reduceEvents(events: RunEvent[]): ScanState {
  const state: ScanState = {
    query: "",
    total: 0,
    scanned: 0,
    topK: 0,
    mode: "keyword",
    currentNames: [],
    hits: new Map(),
    finalHits: [],
    finished: false,
    elapsedMs: 0,
  };

  for (const evt of events) {
    const d = (evt.data ?? {}) as Record<string, unknown>;
    switch (evt.type) {
      case "capability_scan_start":
        state.query = str(d.query);
        state.total = num(d.total);
        state.topK = num(d.top_k);
        state.mode = str(d.mode) || "keyword";
        state.scanned = 0;
        state.currentNames = [];
        state.hits.clear();
        state.finalHits = [];
        state.finished = false;
        state.elapsedMs = 0;
        break;
      case "capability_scan_progress":
        state.scanned = num(d.scanned, state.scanned);
        if (!state.total) state.total = num(d.total);
        state.currentNames = strArray(d.current_names);
        break;
      case "capability_scan_hit": {
        const hit = pickHitFromPayload(d);
        if (hit.name) state.hits.set(hit.name, hit);
        break;
      }
      case "capability_scan_end": {
        state.finished = true;
        state.scanned = num(d.total_scanned, state.scanned);
        if (!state.total) state.total = num(d.total);
        state.elapsedMs = num(d.elapsed_ms, state.elapsedMs);
        const rawHits = Array.isArray(d.hits) ? (d.hits as Array<Record<string, unknown>>) : [];
        if (rawHits.length > 0) {
          state.finalHits = rawHits.map((row) => pickHitFromPayload(row));
        } else {
          state.finalHits = Array.from(state.hits.values());
        }
        break;
      }
      default:
        break;
    }
  }
  return state;
}

function HitRow({ hit, highlighted = false }: { hit: ScanHit; highlighted?: boolean }) {
  const terms = (hit.matchedTerms ?? []).slice(0, 4);
  return (
    <li
      className={`capability-scan-card__hit${highlighted ? " capability-scan-card__hit--new" : ""}`}
      title={hit.title || hit.name}
    >
      <span className="capability-scan-card__hit-name">{hit.name}</span>
      {typeof hit.score === "number" ? (
        <span className="capability-scan-card__hit-score">score {hit.score}</span>
      ) : null}
      {terms.length > 0 ? (
        <span className="capability-scan-card__hit-terms">
          {terms.map((t) => (
            <span key={t} className="capability-scan-card__hit-term">
              {t}
            </span>
          ))}
        </span>
      ) : null}
      {hit.invokeMode ? (
        <span
          className={`capability-scan-card__hit-mode capability-scan-card__hit-mode--${hit.invokeMode}`}
        >
          {hit.invokeMode}
        </span>
      ) : null}
    </li>
  );
}

export function CapabilityScanCard({
  events,
  isLive = false,
}: {
  events: RunEvent[];
  isLive?: boolean;
}) {
  const state = useMemo(() => reduceEvents(events), [events]);
  const [expanded, setExpanded] = useState<boolean>(true);
  const [hasAutoCollapsed, setHasAutoCollapsed] = useState<boolean>(false);
  const lastHitNameRef = useRef<string>("");

  const hitsForDisplay: ScanHit[] = useMemo(() => {
    if (state.finished && state.finalHits.length > 0) return state.finalHits;
    return Array.from(state.hits.values());
  }, [state.finished, state.finalHits, state.hits]);

  const newestName = hitsForDisplay.length > 0 ? hitsForDisplay[hitsForDisplay.length - 1].name : "";

  useEffect(() => {
    if (newestName) {
      lastHitNameRef.current = newestName;
    }
  }, [newestName]);

  useEffect(() => {
    if (!state.finished || hasAutoCollapsed) return;
    const t = window.setTimeout(() => {
      setExpanded(false);
      setHasAutoCollapsed(true);
    }, COLLAPSE_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [state.finished, hasAutoCollapsed]);

  const progressPct = state.total > 0 ? Math.min(100, Math.round((state.scanned / state.total) * 100)) : 0;
  const summaryHits = hitsForDisplay.length;
  const totalLabel = state.total > 0 ? state.total.toLocaleString() : "?";

  if (state.finished && !expanded) {
    return (
      <button
        type="button"
        className="capability-scan-card capability-scan-card--collapsed"
        onClick={() => setExpanded(true)}
        title={state.query ? `查询：${state.query}` : undefined}
      >
        <span className="capability-scan-card__collapsed-icon" aria-hidden>
          <Icon name="search-normal" size={16} />
        </span>
        <span className="capability-scan-card__collapsed-text">
          已从 {totalLabel} 个 COMSOL 操作中选出 {summaryHits} 个相关能力
        </span>
        {state.elapsedMs > 0 ? (
          <span className="capability-scan-card__collapsed-meta">{state.elapsedMs} ms</span>
        ) : null}
        <span className="capability-scan-card__collapsed-arrow" aria-hidden>
          <Icon name="arrow-right-01" size={14} />
        </span>
      </button>
    );
  }

  const isScanning = !state.finished && isLive;

  return (
    <section
      className={`capability-scan-card${isScanning ? " capability-scan-card--scanning" : ""}${state.finished ? " capability-scan-card--done" : ""}`}
    >
      <header className="capability-scan-card__header">
        <div className="capability-scan-card__header-main">
          <span className="capability-scan-card__icon" aria-hidden>
            <Icon name="search-normal" size={16} />
          </span>
          <div className="capability-scan-card__title-block">
            <h4 className="capability-scan-card__title">
              {state.finished ? "操作扫描完成" : "正在扫描 COMSOL 操作"}
            </h4>
            <p className="capability-scan-card__subtitle">
              已扫 {state.scanned.toLocaleString()} / {totalLabel}
              {state.finished ? ` · 选出 ${summaryHits} 项` : ` · 命中 ${summaryHits} 项`}
              {state.elapsedMs > 0 ? ` · ${state.elapsedMs} ms` : ""}
            </p>
          </div>
        </div>
        {state.finished ? (
          <button
            type="button"
            className="capability-scan-card__toggle"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "收起" : "展开"}
          </button>
        ) : null}
      </header>

      <div className="capability-scan-card__progress">
        <div
          className="capability-scan-card__progress-bar"
          style={{ width: `${progressPct}%` }}
          aria-hidden
        />
        <span className="capability-scan-card__progress-label">{progressPct}%</span>
      </div>

      <div className="capability-scan-card__body">
        <div className="capability-scan-card__column capability-scan-card__column--current">
          <span className="capability-scan-card__column-label">正在查看</span>
          <ul className="capability-scan-card__current-list" aria-hidden={state.finished}>
            {state.currentNames.length === 0 ? (
              <li className="capability-scan-card__current-empty">
                {state.finished ? "已扫描完毕" : "准备扫描…"}
              </li>
            ) : (
              state.currentNames.map((name, idx) => (
                <li
                  key={`${name}-${idx}`}
                  className="capability-scan-card__current-item"
                  style={{ opacity: 0.4 + idx * 0.12 }}
                >
                  {name}
                </li>
              ))
            )}
          </ul>
        </div>

        <div className="capability-scan-card__column capability-scan-card__column--hits">
          <span className="capability-scan-card__column-label">
            {state.finished ? "最终入选" : "命中候选"}
          </span>
          {hitsForDisplay.length === 0 ? (
            <p className="capability-scan-card__hits-empty">尚未命中任何候选</p>
          ) : (
            <ul className="capability-scan-card__hits">
              {hitsForDisplay.map((hit) => (
                <HitRow
                  key={hit.name}
                  hit={hit}
                  highlighted={!state.finished && hit.name === lastHitNameRef.current}
                />
              ))}
            </ul>
          )}
        </div>
      </div>

      {state.query ? (
        <footer className="capability-scan-card__footer">
          <span className="capability-scan-card__footer-label">查询：</span>
          <span className="capability-scan-card__footer-text">{state.query}</span>
        </footer>
      ) : null}
    </section>
  );
}
