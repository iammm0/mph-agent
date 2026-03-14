import { useEffect, useMemo, useState } from "react";
import type { ApiWrapperItem } from "../../lib/api";
import { listOfficialApis } from "../../lib/api";
import { useAppState } from "../../context/AppStateContext";

interface ApiBrowserDialogProps {
  onClose: () => void;
}

export function ApiBrowserDialog({ onClose }: ApiBrowserDialogProps) {
  const { dispatch } = useAppState();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ApiWrapperItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = (q?: string) => {
    setLoading(true);
    setError(null);
    listOfficialApis({ query: q?.trim() || undefined, limit: 300, offset: 0 })
      .then((res) => {
        if (!res.ok) {
          setError(res.message || "加载 API 列表失败");
          setItems([]);
          return;
        }
        setItems(res.apis ?? []);
      })
      .catch((e) => {
        setError(String(e));
        setItems([]);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSearch = () => {
    loadData(query);
  };

  const handleSelect = (item: ApiWrapperItem) => {
    // 生成一个带 call_official_api 步骤的自然语言模板，写入当前输入框草稿
    const template = [
      "请在本次建模任务中增加一个 call_official_api 步骤，调用下列 COMSOL 官方 Java API 包装函数：",
      "",
      `- wrapper_name: ${item.wrapper_name}`,
      `- owner: ${item.owner}`,
      `- method_name: ${item.method_name}`,
      "",
      "你需要：",
      "1) 根据当前模型与用户需求，合理设置 target_path（从 model 出发的链式路径）；",
      "2) 在 parameters.args 中填入合适的参数；",
      "3) 在 ReAct 计划的 required_steps 中加入 call_official_api，并在该步骤的 parameters.wrapper 中写入上面的 wrapper_name。",
      "",
      "建模需求：",
      "",
    ].join("\n");
    dispatch({ type: "SET_EDITING_DRAFT", text: template });
    onClose();
  };

  const grouped = useMemo(() => {
    // 按 owner 简单分组，以便稍微好看一点
    const map = new Map<string, ApiWrapperItem[]>();
    for (const it of items) {
      const key = it.owner || "Unknown";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(it);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  return (
    <>
      <div className="dialog-header">官方 API 浏览 / 搜索</div>
      <div className="dialog-body">
        <p className="dialog-hint" style={{ marginBottom: "8px" }}>
          已集成的 COMSOL 官方 Java API 包装（api_*），可用于 call_official_api 步骤的 wrapper_name。
        </p>
        <div className="dialog-row" style={{ gap: "8px", alignItems: "center" }}>
          <input
            type="text"
            className="dialog-input"
            placeholder="按 wrapper / 类名 / 方法名 搜索，例如 remove study / export / geometry"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleSearch();
              }
            }}
          />
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={handleSearch}
            disabled={loading}
          >
            搜索
          </button>
        </div>

        {loading && <div className="dialog-row">正在加载 API 列表...</div>}
        {error && (
          <div className="dialog-row" style={{ color: "#c00" }}>
            加载失败：{error}
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="dialog-row">暂无匹配的 API。</div>
        )}

        {!loading && !error && items.length > 0 && (
          <div className="dialog-section" style={{ maxHeight: "320px", overflow: "auto", marginTop: "8px" }}>
            {grouped.map(([owner, list]) => (
              <div key={owner} style={{ marginBottom: "8px" }}>
                <div className="dialog-section-title-small">{owner}</div>
                {list.map((it) => (
                  <button
                    key={it.wrapper_name}
                    type="button"
                    className="dialog-row-btn"
                    onClick={() => handleSelect(it)}
                  >
                    <span className="dialog-row-key">{it.wrapper_name}</span>
                    <span className="dialog-row-val">{it.method_name}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

        <div className="dialog-actions" style={{ marginTop: "12px" }}>
          <button type="button" className="dialog-btn" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </>
  );
}

