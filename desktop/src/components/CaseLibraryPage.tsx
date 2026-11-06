import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useAppState } from "../context/AppStateContext";
import {
  CASE_LIBRARY_TARGET_VERSION,
  fetchCaseLibrary,
  fetchCaseLibrarySyncStatus,
  formatCaseLibraryTime,
  startCaseLibrarySync,
  type CaseLibraryItem,
  type CaseLibrarySyncState,
} from "../lib/caseLibrary";
import { trackCaseLibraryRecord, type CaseLibraryRecordAction } from "../lib/caseLibraryRecords";

const CASE_LIBRARY_STATUS_COLLAPSED_KEY = "mph-agent-case-library-status-collapsed";

function buildParsePrompt(item: CaseLibraryItem): string {
  return [
    "请解析这个 COMSOL 官方案例，并给出可复现的建模步骤与关键参数：",
    `案例标题：${item.title}`,
    `案例分类：${item.category}`,
    `案例版本：${item.latestVersion || CASE_LIBRARY_TARGET_VERSION}`,
    `官方链接：${item.officialUrl}`,
    `下载链接：${item.downloadUrl}`,
    "补充要求：",
    `0. 请按 ${CASE_LIBRARY_TARGET_VERSION} 的界面、模块命名和案例文件来复现`,
    "1. 先说明适合的物理场接口和耦合关系",
    "2. 再给出几何、材料、边界条件、研究类型",
    "3. 最后给出在当前项目里可直接执行的建模指令草案",
  ].join("\n");
}

function renderSyncSummary(syncState: CaseLibrarySyncState | null): string {
  if (!syncState) return `本地 ${CASE_LIBRARY_TARGET_VERSION} 案例库尚未同步`;
  if (syncState.running) {
    const detail =
      typeof syncState.detailCompleted === "number" && typeof syncState.detailTotal === "number"
        ? `详情 ${syncState.detailCompleted}/${syncState.detailTotal}`
        : null;
    const indexed = syncState.savedItems > 0 ? `已写入 ${syncState.savedItems} 条` : null;
    return [syncState.message || "案例库同步中...", detail, indexed].filter(Boolean).join(" · ");
  }
  if (syncState.status === "completed") {
    return `案例库同步完成 · 当前索引 ${syncState.indexedItems || syncState.savedItems} 条`;
  }
  if (syncState.status === "error") {
    return syncState.message || "案例库同步失败";
  }
  return syncState.message || "本地案例库尚未同步";
}

export function CaseLibraryPage() {
  const { dispatch } = useAppState();
  const [items, setItems] = useState<CaseLibraryItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("全部");
  const [syncState, setSyncState] = useState<CaseLibrarySyncState | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [statusText, setStatusText] = useState("");
  const [statusCollapsed, setStatusCollapsed] = useState(() => {
    try {
      return typeof localStorage !== "undefined" && localStorage.getItem(CASE_LIBRARY_STATUS_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(CASE_LIBRARY_STATUS_COLLAPSED_KEY, statusCollapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [statusCollapsed]);

  const loadCases = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    const result = await fetchCaseLibrary({ limit: 2000 });
    setItems(result.items);
    setGeneratedAt(result.generatedAt);
    if (!result.ok) {
      setStatusText(result.message);
    } else if (!silent) {
      setStatusText("");
    }
    if (!silent) setLoading(false);
  }, []);

  const loadSyncStatus = useCallback(async () => {
    const status = await fetchCaseLibrarySyncStatus();
    setSyncState(status);
    setSyncing(status?.running === true);
    if (status?.generatedAt) {
      setGeneratedAt(status.generatedAt);
    }
    return status;
  }, []);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      await loadSyncStatus();
      await loadCases({ silent: true });
      setLoading(false);
    })();
  }, [loadCases, loadSyncStatus]);

  useEffect(() => {
    if (!syncing) return undefined;
    const timer = window.setInterval(() => {
      void loadSyncStatus();
      void loadCases({ silent: true });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [syncing, loadCases, loadSyncStatus]);

  const categories = useMemo(() => {
    const set = new Set<string>(["全部"]);
    items.forEach((item) => set.add(item.category));
    return Array.from(set);
  }, [items]);

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    return items.filter((item) => {
      if (category !== "全部" && item.category !== category) return false;
      if (!q) return true;
      const haystack = `${item.title} ${item.summary} ${item.tags.join(" ")}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [items, keyword, category]);

  const selectedCase = useMemo(
    () => items.find((item) => item.id === selectedCaseId) ?? null,
    [items, selectedCaseId]
  );

  const openExternalPath = useCallback(async (path: string, successText: string) => {
    try {
      await invoke("open_path", { path });
      setStatusText(successText);
    } catch (error) {
      setStatusText(`无法打开链接：${String(error)}`);
    }
  }, []);

  const handleCaseLink = useCallback(async (item: CaseLibraryItem, action: CaseLibraryRecordAction) => {
    const url = action === "download" ? item.downloadUrl : item.officialUrl;
    await openExternalPath(url, action === "download" ? "已在默认浏览器触发案例下载" : "已打开官方案例库");
    if (action === "download") {
      trackCaseLibraryRecord(item, action);
    }
  }, [openExternalPath]);

  const openCaseDetail = useCallback((item: CaseLibraryItem) => {
    setSelectedCaseId(item.id);
    trackCaseLibraryRecord(item, "view");
    setStatusText("已打开程序内详情");
  }, []);

  const closeCaseDetail = useCallback(() => {
    setSelectedCaseId(null);
    setStatusText("");
  }, []);

  const handleQuickParse = useCallback(
    (item: CaseLibraryItem) => {
      dispatch({ type: "SET_MODE", mode: "plan" });
      dispatch({ type: "SET_EDITING_DRAFT", text: buildParsePrompt(item) });
      dispatch({ type: "SET_VIEW", view: "session" });
    },
    [dispatch]
  );

  const handleRefresh = useCallback(async () => {
    setStatusText("");
    await loadSyncStatus();
    await loadCases();
  }, [loadCases, loadSyncStatus]);

  const handleSync = useCallback(async () => {
    setStatusText("");
    setSyncing(true);
    const state = await startCaseLibrarySync({ workers: 4, delayMs: 100 });
    if (!state) {
      setSyncing(false);
      setStatusText("案例库同步启动失败");
      return;
    }
    setSyncState(state);
    setSyncing(state.running);
    await loadCases({ silent: true });
  }, [loadCases]);

  const emptyText = useMemo(() => {
    if (loading && items.length === 0) return "正在加载案例库...";
    if (syncing) return "案例库正在同步，卡片会逐步出现...";
    if (items.length === 0) {
      return `本地案例库还没有数据，先点击“同步案例库”抓取 ${CASE_LIBRARY_TARGET_VERSION} 官方案例。`;
    }
    return "未找到匹配的案例";
  }, [items.length, loading, syncing]);

  useEffect(() => {
    if (!selectedCaseId) return;
    if (items.some((item) => item.id === selectedCaseId)) return;
    setSelectedCaseId(null);
  }, [items, selectedCaseId]);

  return (
    <div className="case-library">
      <div className="library-page-header">
        <div>
          <h2 className="library-page-title">案例库</h2>
        </div>
        <div className="library-page-actions">
          {selectedCase ? (
            <button type="button" className="dialog-btn secondary" onClick={closeCaseDetail}>
              返回上一页
            </button>
          ) : (
            <>
              <button
                type="button"
                className="dialog-btn secondary"
                onClick={handleRefresh}
                disabled={loading || syncing}
              >
                {loading ? "刷新中..." : "刷新"}
              </button>
              <button type="button" className="dialog-btn primary" onClick={handleSync} disabled={syncing}>
                {syncing ? "同步中..." : "同步案例库"}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="case-library-toolbar">
        <input
          className="case-library-search"
          type="text"
          placeholder="搜索案例标题、摘要或标签..."
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <select
          className="case-library-category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </div>

      <div
        className={`case-library-status ${syncState?.status === "error" ? "case-library-status--error" : ""} ${
          statusCollapsed ? "case-library-status--collapsed" : ""
        }`}
      >
        <div className="case-library-status__body">
          <div className="case-library-status__main">
            <span className="case-library-status__title">{renderSyncSummary(syncState)}</span>
            {!statusCollapsed && (
              <>
                <span className="case-library-status__meta">目标版本：{CASE_LIBRARY_TARGET_VERSION}</span>
                {generatedAt && (
                  <span className="case-library-status__meta">索引时间：{formatCaseLibraryTime(generatedAt)}</span>
                )}
              </>
            )}
          </div>
          {!statusCollapsed && statusText ? <span className="case-library-status__meta case-library-status__hint">{statusText}</span> : null}
        </div>
        <button
          type="button"
          className="case-library-status__toggle"
          onClick={() => setStatusCollapsed((c) => !c)}
          aria-expanded={!statusCollapsed}
          aria-label={statusCollapsed ? "展开案例库状态" : "折叠案例库状态"}
          title={statusCollapsed ? "展开案例库状态" : "折叠案例库状态"}
        >
          {statusCollapsed ? "▼" : "▲"}
        </button>
      </div>

      {selectedCase ? (
        <section className="case-detail">
          <div className="case-detail-hero">
            <div className="case-detail-hero__body">
              <div className="case-detail-hero__header">
                <div>
                  <span className="case-detail-kicker">案例详情</span>
                  <h3 className="case-detail-title">{selectedCase.title}</h3>
                  <p className="case-detail-summary">{selectedCase.summary}</p>
                </div>
                <span className="case-card-category">{selectedCase.category}</span>
              </div>

              <div className="case-card-tags">
                {selectedCase.tags.map((tag) => (
                  <span className="case-card-tag" key={`${selectedCase.id}-${tag}`}>
                    {tag}
                  </span>
                ))}
              </div>

              <div className="case-card-actions">
                <button
                  type="button"
                  className="dialog-btn secondary"
                  onClick={() => void handleCaseLink(selectedCase, "view")}
                >
                  官方案例库
                </button>
                <button
                  type="button"
                  className="dialog-btn secondary"
                  onClick={() => void handleCaseLink(selectedCase, "download")}
                >
                  下载案例
                </button>
                <button type="button" className="dialog-btn primary" onClick={() => handleQuickParse(selectedCase)}>
                  一键转解析
                </button>
              </div>
            </div>

            {selectedCase.imageUrl && (
              <div className="case-detail-hero__media">
                <img className="case-detail-image" src={selectedCase.imageUrl} alt={selectedCase.title} />
              </div>
            )}
          </div>

          <div className="case-detail-grid">
            <section className="case-detail-panel">
              <h4>案例信息</h4>
              <div className="case-detail-meta">
                <div>
                  <span>案例 ID</span>
                  <strong>{selectedCase.applicationId || selectedCase.id}</strong>
                </div>
                <div>
                  <span>Slug</span>
                  <strong>{selectedCase.slug || "未记录"}</strong>
                </div>
                <div>
                  <span>目标版本</span>
                  <strong>{selectedCase.latestVersion || CASE_LIBRARY_TARGET_VERSION}</strong>
                </div>
                <div>
                  <span>主下载</span>
                  <strong>{selectedCase.downloadUrl}</strong>
                </div>
              </div>
            </section>

            <section className="case-detail-panel">
              <h4>关联模块</h4>
              {selectedCase.products.length > 0 ? (
                <div className="case-detail-link-list">
                  {selectedCase.products.map((product) => (
                    <button
                      key={`${selectedCase.id}-${product.name}`}
                      type="button"
                      className="case-detail-link"
                      onClick={() => void openExternalPath(product.url, `已打开模块页面：${product.name}`)}
                    >
                      <span>{product.name}</span>
                      <span>查看模块</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="case-detail-empty">当前案例没有记录关联模块。</p>
              )}
            </section>

            <section className="case-detail-panel">
              <h4>可下载文件</h4>
              <p className="case-detail-empty">当前列表仅保留 {CASE_LIBRARY_TARGET_VERSION} 对应的案例文件。</p>
              {selectedCase.downloads.length > 0 ? (
                <div className="case-detail-downloads">
                  {selectedCase.downloads.map((download) => (
                    <button
                      key={`${selectedCase.id}-${download.url}`}
                      type="button"
                      className="case-detail-download"
                      onClick={() =>
                        void openExternalPath(download.url, `已打开下载链接：${download.filename || selectedCase.title}`)
                      }
                    >
                      <strong>{download.filename || download.url}</strong>
                      <span>
                        {[download.version, download.fileType, download.size].filter(Boolean).join(" · ") || "下载文件"}
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="case-detail-empty">当前案例没有解析到下载文件列表。</p>
              )}
            </section>

            <section className="case-detail-panel">
              <h4>补充链接</h4>
              <div className="case-card-actions">
                <button
                  type="button"
                  className="dialog-btn secondary"
                  onClick={() => void handleCaseLink(selectedCase, "view")}
                >
                  打开中文官方页
                </button>
                {selectedCase.englishUrl && (
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={() => void openExternalPath(selectedCase.englishUrl, "已打开英文页面")}
                  >
                    英文页面
                  </button>
                )}
                {selectedCase.referencePdfUrl && (
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={() => void openExternalPath(selectedCase.referencePdfUrl, "已打开参考 PDF")}
                  >
                    参考 PDF
                  </button>
                )}
              </div>
            </section>
          </div>
        </section>
      ) : (
        <div className="case-library-list">
          {filtered.length === 0 ? (
            <div className="case-library-empty">{emptyText}</div>
          ) : (
            filtered.map((item) => (
              <article
                key={item.id}
                className="case-card case-card--interactive"
                role="button"
                tabIndex={0}
                onClick={() => openCaseDetail(item)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openCaseDetail(item);
                  }
                }}
              >
                <div className="case-card-head">
                  <h3 className="case-card-title">{item.title}</h3>
                  <span className="case-card-category">{item.category}</span>
                </div>
                <p className="case-card-summary">{item.summary}</p>
                <div className="case-card-tags">
                  {item.tags.map((tag) => (
                    <span className="case-card-tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="case-card-actions">
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleCaseLink(item, "view");
                    }}
                  >
                    官方案例库
                  </button>
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleCaseLink(item, "download");
                    }}
                  >
                    下载案例
                  </button>
                  <button
                    type="button"
                    className="dialog-btn primary"
                    onClick={(event) => {
                      event.stopPropagation();
                      handleQuickParse(item);
                    }}
                  >
                    一键转解析
                  </button>
                </div>
              </article>
            ))
          )}
        </div>
      )}
    </div>
  );
}
