import { useCallback, useEffect, useMemo, useState } from "react";
import type { OpsCatalogItem } from "../lib/types";
import { fetchOpsCatalog } from "../lib/opsCatalog";

function getOpKey(item: OpsCatalogItem): string {
  return `${item.invoke_mode}:${item.category}:${item.label}:${item.recommended_action}`;
}

function schemaTypeLabel(value: unknown): string {
  if (typeof value === "string") return value.replace(/\?$/, "");
  return "";
}

function calledMethod(item: OpsCatalogItem): string {
  const example = item.examples?.[0];
  const owner = typeof example?.owner === "string" ? example.owner : "";
  const method = typeof example?.method_name === "string" ? example.method_name : "";
  if (owner && method) return `${owner}.${method}`;
  if (method) return method;
  if (item.recommended_action && item.recommended_action !== "call_official_api") {
    return item.recommended_action;
  }
  return "";
}

const GENERIC_WRAPPER_PARAMS = new Set(["model_path", "args", "target_path"]);

function visibleParams(item: OpsCatalogItem): Array<{ name: string; type: string }> {
  const schema = item.params_schema;
  if (!schema || typeof schema !== "object") return [];
  return Object.entries(schema)
    .filter(([name]) => !GENERIC_WRAPPER_PARAMS.has(name))
    .map(([name, value]) => ({ name, type: schemaTypeLabel(value) }));
}

function buildSearchText(item: OpsCatalogItem): string {
  return [
    item.category,
    item.label,
    item.invoke_mode,
    item.recommended_action,
    item.params_schema ? JSON.stringify(item.params_schema) : "",
    item.examples ? JSON.stringify(item.examples) : "",
  ]
    .join(" ")
    .toLowerCase();
}

export function OpsCatalogPage() {
  const [items, setItems] = useState<OpsCatalogItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("全部");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);

    const result = await fetchOpsCatalog({ limit: 0, offset: 0, wrappersOnly: true });
    if (!result.ok) {
      setItems([]);
      setCategories([]);
      setError(result.message || "加载操作清单失败");
      setLoading(false);
      return;
    }

    setItems(result.items);
    setCategories(result.categories);
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return items.filter((item) => {
      if (category !== "全部" && item.category !== category) return false;
      if (!normalizedQuery) return true;
      return buildSearchText(item).includes(normalizedQuery);
    });
  }, [items, query, category]);

  const grouped = useMemo(() => {
    const map = new Map<string, OpsCatalogItem[]>();

    for (const item of filtered) {
      const key = item.category || "未分类";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(item);
    }

    const orderedCategories = categories.length > 0 ? categories : Array.from(map.keys());
    const groups = orderedCategories
      .map((groupName) => ({
        category: groupName,
        items: map.get(groupName) ?? [],
      }))
      .filter((group) => group.items.length > 0);

    const extraGroups = Array.from(map.entries())
      .filter(([groupName]) => !orderedCategories.includes(groupName))
      .map(([groupName, groupItems]) => ({ category: groupName, items: groupItems }));

    return [...groups, ...extraGroups];
  }, [filtered, categories]);

  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedKey(null);
      return;
    }

    const selectedStillVisible = filtered.some((item) => getOpKey(item) === selectedKey);
    if (!selectedStillVisible) {
      setSelectedKey(getOpKey(filtered[0]));
    }
  }, [filtered, selectedKey]);

  const selectedItem = useMemo(
    () => filtered.find((item) => getOpKey(item) === selectedKey) ?? null,
    [filtered, selectedKey]
  );

  const categoryCount = useMemo(() => new Set(items.map((item) => item.category)).size, [items]);

  return (
    <div className="ops-catalog-page">
      <div className="library-page-header">
        <div>
          <h2 className="library-page-title">COMSOL 可执行操作清单</h2>
          <p className="library-page-desc">
            这里列出当前已加载的 COMSOL 6.3 Java API 包装方法（逐条对应可调用入口），不包含聊天、设置或导航命令。
            高层建模动作（如 create_geometry）由规划与执行管线调度，不在此清单重复罗列。
          </p>
        </div>
        <div className="library-page-actions">
          <button type="button" className="dialog-btn secondary" onClick={() => setQuery(searchInput.trim())}>
            搜索
          </button>
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={() => {
              setSearchInput("");
              setQuery("");
              setCategory("全部");
            }}
          >
            清空筛选
          </button>
          <button type="button" className="dialog-btn primary" onClick={() => void loadCatalog()} disabled={loading}>
            {loading ? "刷新中..." : "刷新清单"}
          </button>
        </div>
      </div>

      <div className="ops-summary-grid">
        <div className="ops-summary-card">
          <span className="ops-summary-card__label">COMSOL API 条目</span>
          <strong>{items.length}</strong>
          <span className="ops-summary-card__hint">当前已加载的包装方法总数</span>
        </div>
        <div className="ops-summary-card">
          <span className="ops-summary-card__label">分类数量</span>
          <strong>{categoryCount}</strong>
          <span className="ops-summary-card__hint">定义、几何、材料、物理场等</span>
        </div>
      </div>

      <div className="ops-toolbar">
        <input
          className="case-library-search"
          type="text"
          placeholder="搜索操作名或方法"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              setQuery(searchInput.trim());
            }
          }}
        />
        <select className="case-library-category" value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="全部">全部分类</option>
          {categories.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="skills-banner skills-banner--error">{error}</div>}

      {loading ? (
        <div className="case-library-empty">正在加载操作清单...</div>
      ) : filtered.length === 0 ? (
        <div className="case-library-empty">当前筛选条件下没有匹配的操作。</div>
      ) : (
        <div className="ops-layout">
          <section className="ops-list-panel">
            <div className="ops-list-panel__head">
              <div>
                <h3 className="ops-section-title">COMSOL 操作目录</h3>
                <p className="ops-section-copy">
                  当前显示 {filtered.length} / {items.length} 条。左侧每一条都是当前可直接执行到 COMSOL 的真实操作。
                </p>
              </div>
            </div>

            <div className="ops-list-scroll">
              {grouped.map((group) => (
                <section key={group.category} className="ops-category-block">
                  <div className="ops-category-title">
                    <span>{group.category}</span>
                    <span>{group.items.length}</span>
                  </div>
                  <div className="ops-item-list">
                    {group.items.map((item) => {
                      const itemKey = getOpKey(item);
                      const method = calledMethod(item);
                      const active = itemKey === selectedKey;

                      return (
                        <button
                          key={itemKey}
                          type="button"
                          className={`ops-item-card ${active ? "is-active" : ""}`}
                          onClick={() => setSelectedKey(itemKey)}
                        >
                          <span className="ops-item-card__title">{item.label}</span>
                          {method ? <span className="ops-item-card__action">{method}</span> : null}
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          </section>

          <aside className="ops-detail-panel">
            {selectedItem ? (
              <>
                <div className="ops-detail-head">
                  <div>
                    <span className="skills-page-kicker">{selectedItem.category}</span>
                    <h3 className="skills-page-title">{selectedItem.label}</h3>
                    {calledMethod(selectedItem) ? (
                      <p className="skills-page-desc">{calledMethod(selectedItem)}</p>
                    ) : null}
                  </div>
                </div>

                {visibleParams(selectedItem).length > 0 ? (
                  <section className="ops-detail-section">
                    <h4>需要填写</h4>
                    <div className="ops-schema-list">
                      {visibleParams(selectedItem).map((param) => (
                        <div key={param.name} className="ops-schema-item">
                          <span className="ops-schema-item__name">{param.name}</span>
                          {param.type ? <span className="ops-schema-item__value">{param.type}</span> : null}
                        </div>
                      ))}
                    </div>
                  </section>
                ) : (
                  <p className="ops-detail-empty">这项操作按名称直接调用，没有额外要填的参数。</p>
                )}
              </>
            ) : (
              <div className="case-library-empty">请选择一条操作查看详细信息。</div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
