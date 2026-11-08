import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useAppState } from "../../context/AppStateContext";
import { MphbWorkflowGraph, statusClass } from "../MphbWorkflowGraph";
import type { MphbPreview } from "../../lib/types";

function openPath(path: string) {
  invoke("open_path", { path }).catch(() => {
    invoke("open_in_folder", { path }).catch(() => {});
  });
}

export function MphbPreviewDialog({ onClose }: { onClose: () => void }) {
  const { state, dispatch } = useAppState();
  const path = state.mphbPreviewPath;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [doc, setDoc] = useState<MphbPreview | null>(state.mphbPreview);
  const [flowView, setFlowView] = useState(true);

  useEffect(() => {
    if (!path) {
      setError("未指定 .mphb 文件路径");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void invoke<{
      ok: boolean;
      message: string;
      mphb?: MphbPreview | null;
    }>("bridge_send", {
      cmd: "mphb_open",
      payload: { path },
    })
      .then((res) => {
        if (cancelled) return;
        if (!res.ok || !res.mphb) {
          setError(res.message || "无法打开构建过程文件");
          setDoc(null);
          return;
        }
        setDoc(res.mphb);
        dispatch({ type: "SET_MPHB_PREVIEW", path, preview: res.mphb });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setDoc(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, dispatch]);

  return (
    <>
      <div className="dialog-header">构建过程预览 · .mphb</div>
      <div className="dialog-body mphb-preview-body">
        {loading && <p className="dialog-hint">正在解析构建过程…</p>}
        {error && !loading && (
          <p className="dialog-hint mphb-preview-error" role="alert">
            {error}
          </p>
        )}
        {doc && !loading && (
          <>
            <div className="mphb-preview-meta">
              <h3 className="mphb-preview-title">{doc.title || "未命名构建过程"}</h3>
              <div className="mphb-preview-badges">
                <span
                  className={`mphb-status ${doc.success ? "mphb-status--ok" : "mphb-status--err"}`}
                >
                  {doc.success ? "成功" : "未成功"}
                </span>
                <span className="mphb-meta-chip">
                  {doc.step_count ?? doc.steps?.length ?? 0} 步
                </span>
                <span className="mphb-meta-chip">
                  {doc.operation_count ?? doc.operations?.length ?? 0} 条操作
                </span>
              </div>
              {doc.created_at && (
                <p className="mphb-preview-sub">生成时间：{doc.created_at}</p>
              )}
              {doc.user_input && (
                <p className="mphb-preview-sub">需求：{doc.user_input}</p>
              )}
              {doc.plan_description && doc.plan_description !== doc.user_input && (
                <p className="mphb-preview-sub">计划：{doc.plan_description}</p>
              )}
              {doc.error && (
                <p className="mphb-preview-error" role="alert">
                  {doc.error}
                </p>
              )}
              {(doc.path || path) && (
                <code className="mphb-preview-path" title={doc.path || path || ""}>
                  {doc.path || path}
                </code>
              )}
            </div>

            {doc.model_path && (
              <div className="mphb-preview-model">
                <div className="dialog-section-title">关联模型</div>
                <code className="mphb-preview-path" title={doc.model_path}>
                  {doc.model_path}
                </code>
                <div className="mphb-preview-actions">
                  <button
                    type="button"
                    className="dialog-btn primary"
                    onClick={() => openPath(doc.model_path!)}
                  >
                    打开 .mph
                  </button>
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={() =>
                      invoke("open_in_folder", { path: doc.model_path }).catch(() => {})
                    }
                  >
                    打开所在目录
                  </button>
                </div>
              </div>
            )}

            <div className="dialog-section-title mphb-flow-head">
              <span>建模步骤</span>
              {(doc.steps?.length ?? 0) > 0 && (
                <div className="mphb-flow-toggle">
                  <button
                    type="button"
                    className={flowView ? "on" : ""}
                    onClick={() => setFlowView(true)}
                  >
                    流程图
                  </button>
                  <button
                    type="button"
                    className={flowView ? "" : "on"}
                    onClick={() => setFlowView(false)}
                  >
                    列表
                  </button>
                </div>
              )}
            </div>
            {(doc.steps?.length ?? 0) === 0 ? (
              <p className="dialog-hint">无步骤记录（可能仅含操作日志）</p>
            ) : flowView ? (
              <MphbWorkflowGraph
                steps={doc.steps!}
                success={!!doc.success}
                modelPath={doc.model_path}
                userInput={doc.user_input}
                planDescription={doc.plan_description}
              />
            ) : (
              <ol className="mphb-step-list">
                {doc.steps!.map((step) => (
                  <li key={`${step.index}-${step.action}`} className="mphb-step-item">
                    <div className="mphb-step-head">
                      <span className="mphb-step-index">{step.index}</span>
                      <span className="mphb-step-label">
                        {step.label || step.action || "步骤"}
                      </span>
                      <span className={`mphb-status ${statusClass(step.status)}`}>
                        {step.status || "pending"}
                      </span>
                    </div>
                    {step.message && (
                      <p className="mphb-step-msg">{step.message}</p>
                    )}
                    {step.step_type && (
                      <p className="mphb-step-type">{step.step_type}</p>
                    )}
                    {step.model_path && (
                      <code className="mphb-step-model" title={step.model_path}>
                        {step.model_path}
                      </code>
                    )}
                  </li>
                ))}
              </ol>
            )}

            {(doc.operations?.length ?? 0) > 0 && (
              <>
                <div className="dialog-section-title">操作日志</div>
                <ul className="mphb-op-list">
                  {doc.operations!.map((op, i) => (
                    <li key={`${op.time}-${i}`} className="mphb-op-item">
                      <span className="mphb-op-time">{op.time}</span>
                      <span className="mphb-op-type">{op.step_type}</span>
                      <span className="mphb-op-msg">
                        {op.message}
                        {op.result ? ` — ${op.result}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>
      <div className="dialog-footer">
        {(doc?.path || path) && (
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={() =>
              invoke("open_in_folder", { path: doc?.path || path }).catch(() => {})
            }
          >
            在资源管理器中显示
          </button>
        )}
        <button type="button" className="dialog-btn primary" onClick={onClose}>
          关闭
        </button>
      </div>
    </>
  );
}
