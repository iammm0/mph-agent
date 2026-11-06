import { useCallback, useEffect, useMemo, useState } from "react";
import type { OpsCatalogItem } from "../../lib/types";
import { fetchOpsCatalog } from "../../lib/opsCatalog";

const PAGE_SIZE = 120;

export function ComsolOpsDialog({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<OpsCatalogItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);

  const fetchCatalog = useCallback(async (nextOffset: number, nextQuery: string) => {
    setLoading(true);
    setError(null);
    const res = await fetchOpsCatalog({
      query: nextQuery || undefined,
      limit: PAGE_SIZE,
      offset: nextOffset,
    });
    if (!res.ok) {
      setError(res.message || "加载操作目录失败");
      setItems([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setItems(res.items);
    setTotal(res.total);
    setCategories(res.categories);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchCatalog(offset, query);
  }, [fetchCatalog, offset, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, OpsCatalogItem[]>();
    for (const item of items) {
      const key = item.category || "未分类";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(item);
    }

    const ordered = categories.length > 0 ? categories : Array.from(map.keys());
    return ordered
      .map((category) => ({ category, items: map.get(category) ?? [] }))
      .filter((group) => group.items.length > 0);
  }, [items, categories]);

  const pageEnd = Math.min(offset + PAGE_SIZE, total);

  return (
    <>
      <div className="dialog-header">支持的 COMSOL 操作目录</div>
      <div className="dialog-body">
        <p className="dialog-hint" style={{ marginBottom: "12px" }}>
          操作目录来自后端动态能力清单（native + wrapper），支持搜索和分页。
        </p>

        <div className="dialog-row" style={{ gap: "8px", marginBottom: "12px" }}>
          <input
            className="dialog-input"
            style={{ flex: 1 }}
            value={searchInput}
            placeholder="搜索 category / label / action..."
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setOffset(0);
                setQuery(searchInput.trim());
              }
            }}
          />
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={() => {
              setOffset(0);
              setQuery(searchInput.trim());
            }}
            disabled={loading}
          >
            搜索
          </button>
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={() => {
              setSearchInput("");
              setQuery("");
              setOffset(0);
            }}
            disabled={loading}
          >
            清空
          </button>
        </div>

        <div className="dialog-row" style={{ marginBottom: "12px" }}>
          <span className="dialog-row-key">分页</span>
          <span className="dialog-row-val">
            {total === 0 ? "0" : `${offset + 1}-${pageEnd}`} / {total}
          </span>
        </div>

        {loading && <p>正在加载操作目录...</p>}
        {error && <p style={{ color: "var(--error)" }}>{error}</p>}
        {!loading && !error && grouped.length === 0 && <p>暂无匹配的能力项。</p>}

        {!loading &&
          !error &&
          grouped.map((group) => (
            <div key={group.category} style={{ marginBottom: "14px" }}>
              <div className="dialog-section-title">{group.category}</div>
              {group.items.map((item, idx) => (
                <div key={`${group.category}-${item.label}-${idx}`} className="dialog-row">
                  <span className="dialog-row-key">{item.label}</span>
                </div>
              ))}
            </div>
          ))}

        <div className="dialog-actions" style={{ marginTop: "16px" }}>
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}
            disabled={loading || offset <= 0}
          >
            上一页
          </button>
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={() => setOffset((v) => (v + PAGE_SIZE < total ? v + PAGE_SIZE : v))}
            disabled={loading || offset + PAGE_SIZE >= total}
          >
            下一页
          </button>
          <button type="button" className="dialog-btn primary" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </>
  );
}
