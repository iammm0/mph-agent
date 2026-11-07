import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface ModelPickerProps {
  apiKey: string;
  model: string;
  disabled?: boolean;
  /** composer：输入框底栏；field：设置页一行 */
  variant?: "composer" | "field";
  onSelect: (model: string) => void;
}

const MODEL_HINTS: Record<string, string> = {
  "deepseek-flash": "快速 / 默认",
  "deepseek-v4-pro": "更高质量",
};

export function ModelPicker({
  apiKey,
  model,
  disabled = false,
  variant = "composer",
  onSelect,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);

  const probe = useCallback(async () => {
    const key = apiKey.trim();
    if (!key) {
      setModels([]);
      setStatus("请先在设置中填写 API 密钥");
      return;
    }
    setLoading(true);
    setStatus("");
    try {
      const res = await invoke<{
        ok: boolean;
        message: string;
        models?: string[];
      }>("bridge_send", {
        cmd: "deepseek_models",
        payload: { api_key: key },
      });
      const list = (res.models ?? []).filter((item) => item.trim());
      if (res.ok && list.length > 0) {
        setModels(list);
        setStatus("");
      } else {
        setModels([]);
        const message = res.message || "未探测到模型";
        setStatus(
          message.includes("未知命令")
            ? "探测命令尚未加载，请重启桌面端后再试"
            : message
        );
      }
    } catch (error) {
      setModels([]);
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, [apiKey]);

  useEffect(() => {
    if (!open) return;
    void probe();
  }, [open, probe]);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (event: MouseEvent) => {
      const el = wrapRef.current;
      if (el && !el.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = model.trim();
  const options = current && !models.includes(current) ? [current, ...models] : models;
  const label = current || "选择模型";

  return (
    <div
      className={`model-picker model-picker--${variant}`}
      ref={wrapRef}
    >
      <button
        type="button"
        className="model-picker__trigger"
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="listbox"
        title="选择 DeepSeek 模型"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="model-picker__name">{label}</span>
        <span className="model-picker__chevron" aria-hidden="true" />
      </button>
      {open && (
        <div className="model-picker__menu" role="listbox" aria-label="DeepSeek 模型">
          <div className="model-picker__head">
            <span>DeepSeek</span>
            <button
              type="button"
              className="model-picker__refresh"
              onClick={() => void probe()}
              disabled={loading || !apiKey.trim()}
            >
              {loading ? "探测中…" : "重新探测"}
            </button>
          </div>
          {loading && options.length === 0 && (
            <div className="model-picker__status">正在探测模型…</div>
          )}
          {!loading && status && (
            <div className="model-picker__status">{status}</div>
          )}
          {options.map((item) => {
            const hint = MODEL_HINTS[item];
            const selected = item === current;
            return (
              <button
                key={item}
                type="button"
                role="option"
                aria-selected={selected}
                className={`model-picker__option${selected ? " is-selected" : ""}`}
                onClick={() => {
                  onSelect(item);
                  setOpen(false);
                }}
              >
                <span className="model-picker__option-main">
                  <span className="model-picker__option-id">{item}</span>
                  {hint && <span className="model-picker__option-hint">{hint}</span>}
                </span>
                {selected && <span className="model-picker__check">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
