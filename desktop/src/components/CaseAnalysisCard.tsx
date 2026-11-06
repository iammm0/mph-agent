import { invoke } from "@tauri-apps/api/core";
import { useCallback, useMemo } from "react";
import { useAppState } from "../context/AppStateContext";
import type {
  CaseGeneratedData,
  CaseSectionEntry,
  CaseWorkflowStep,
} from "../lib/types";

function formatTime(value: string | undefined): string {
  if (!value) return "未知";
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return value;
  return new Date(ts).toLocaleString("zh-CN");
}

function getFileName(path: string | undefined): string {
  if (!path) return "未命名模型";
  const normalized = path.replace(/\\/g, "/");
  return normalized.slice(normalized.lastIndexOf("/") + 1) || normalized;
}

function toList(value: string[] | undefined): string[] {
  return Array.isArray(value) ? value.filter((item) => Boolean(String(item).trim())) : [];
}

function toSectionEntries(value: CaseSectionEntry[] | undefined): CaseSectionEntry[] {
  return Array.isArray(value) ? value : [];
}

function toWorkflow(value: CaseWorkflowStep[] | undefined): CaseWorkflowStep[] {
  return Array.isArray(value) ? value : [];
}

function collectEntryHints(entry: CaseSectionEntry): string[] {
  const hints: string[] = [];
  if (entry.role) hints.push(entry.role);
  if (entry.purpose) hints.push(entry.purpose);
  if (entry.why) hints.push(entry.why);
  if (entry.quality_hint) hints.push(entry.quality_hint);
  if (Array.isArray(entry.construction_clues)) hints.push(...entry.construction_clues);
  if (Array.isArray(entry.selection_hint)) hints.push(...entry.selection_hint);
  if (Array.isArray(entry.tree_clues)) hints.push(...entry.tree_clues);
  return hints.filter((item) => Boolean(String(item).trim())).slice(0, 4);
}

function openPath(path: string) {
  invoke("open_path", { path }).catch(() => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(path);
    }
  });
}

function openInFolder(path: string) {
  invoke("open_in_folder", { path }).catch(() => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(path);
    }
  });
}

interface CaseAnalysisCardProps {
  caseData: CaseGeneratedData;
  savedPath?: string | null;
}

export function CaseAnalysisCard({
  caseData,
  savedPath,
}: CaseAnalysisCardProps) {
  const { dispatch } = useAppState();
  const globalDefinitions = caseData.global_definitions ?? [];
  const workflowSteps = useMemo(
    () => toWorkflow(caseData.workflow_steps),
    [caseData.workflow_steps]
  );
  const designIntent = useMemo(
    () => toList(caseData.design_intent),
    [caseData.design_intent]
  );
  const editWorkflow = useMemo(
    () => toList(caseData.recommended_edit_workflow),
    [caseData.recommended_edit_workflow]
  );
  const nodeTreeExcerpt = useMemo(
    () => toList(caseData.node_tree_excerpt),
    [caseData.node_tree_excerpt]
  );
  const physicalPrinciples = useMemo(
    () => toList(caseData.physical_principles),
    [caseData.physical_principles]
  );
  const expectedBehaviors = useMemo(
    () => toList(caseData.expected_behaviors),
    [caseData.expected_behaviors]
  );

  const sectionGroups = useMemo(
    () => [
      {
        title: "几何构建",
        items: toSectionEntries(caseData.geometry_setup),
      },
      {
        title: "材料分配",
        items: toSectionEntries(caseData.material_setup),
      },
      {
        title: "物理场配置",
        items: toSectionEntries(caseData.physics_setup),
      },
      {
        title: "网格设置",
        items: toSectionEntries(caseData.mesh_setup),
      },
      {
        title: "研究流程",
        items: toSectionEntries(caseData.study_setup),
      },
      {
        title: "结果输出",
        items: toSectionEntries(caseData.postprocess_setup),
      },
    ],
    [
      caseData.geometry_setup,
      caseData.material_setup,
      caseData.physics_setup,
      caseData.mesh_setup,
      caseData.study_setup,
      caseData.postprocess_setup,
    ]
  );

  const handleContinueEditing = useCallback(() => {
    const prompt =
      caseData.copy_edit_prompt?.trim() ||
      caseData.reusable_user_prompt?.trim() ||
      caseData.context_block?.trim() ||
      "";
    if (!prompt) return;
    dispatch({ type: "SET_EDITING_DRAFT", text: prompt });
  }, [
    caseData.context_block,
    caseData.copy_edit_prompt,
    caseData.reusable_user_prompt,
    dispatch,
  ]);

  return (
    <div className="case-analysis-card">
      <div className="case-analysis-card__hero">
        <div className="case-analysis-card__hero-main">
          <span className="case-analysis-card__kicker">Local .mph Analysis</span>
          <h3 className="case-analysis-card__title">
            {getFileName(caseData.source_model_path)}
          </h3>
          <p className="case-analysis-card__summary">
            {caseData.summary || "已完成本地 COMSOL 模型剖析。"}
          </p>
        </div>
        <div className="case-analysis-card__hero-actions">
          {caseData.source_model_path && (
            <button
              type="button"
              className="assistant-msg-model-btn"
              onClick={() => openInFolder(caseData.source_model_path || "")}
            >
              打开源模型
            </button>
          )}
          {savedPath && (
            <button
              type="button"
              className="assistant-msg-model-btn"
              onClick={() => openPath(savedPath)}
            >
              打开解析 JSON
            </button>
          )}
          {(caseData.copy_edit_prompt ||
            caseData.reusable_user_prompt ||
            caseData.context_block) && (
            <button
              type="button"
              className="assistant-msg-model-btn primary"
              onClick={handleContinueEditing}
            >
              继续修改该模型
            </button>
          )}
        </div>
      </div>

      <div className="case-analysis-card__meta">
        <span>源文件：{caseData.source_model_path || "未知"}</span>
        <span>解析时间：{formatTime(caseData.extracted_at)}</span>
      </div>

      {(physicalPrinciples.length > 0 || expectedBehaviors.length > 0) && (
        <section className="case-analysis-card__section">
          <h4>模型目标与行为</h4>
          <div className="case-analysis-card__tags">
            {physicalPrinciples.map((item) => (
              <span key={`principle-${item}`} className="case-analysis-card__tag">
                {item}
              </span>
            ))}
            {expectedBehaviors.map((item) => (
              <span
                key={`behavior-${item}`}
                className="case-analysis-card__tag case-analysis-card__tag--muted"
              >
                {item}
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="case-analysis-card__section">
        <div className="case-analysis-card__section-head">
          <h4>全局参数</h4>
          <span>{globalDefinitions.length} 项</span>
        </div>
        {globalDefinitions.length > 0 ? (
          <div className="case-analysis-card__table-wrap">
            <table className="case-analysis-card__table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>数值</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {globalDefinitions.map((item) => (
                  <tr key={item.name}>
                    <td>{item.name}</td>
                    <td>{item.value}</td>
                    <td>{item.description || item.unit || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="case-analysis-card__empty">未解析到全局参数。</p>
        )}
      </section>

      {workflowSteps.length > 0 && (
        <section className="case-analysis-card__section">
          <div className="case-analysis-card__section-head">
            <h4>标准建模流程</h4>
            <span>{workflowSteps.length} 步</span>
          </div>
          <ol className="case-analysis-card__workflow">
            {workflowSteps.map((step, index) => (
              <li key={`${step.stage || step.action || index}`}>
                <strong>{step.stage || step.action || `步骤 ${index + 1}`}</strong>
                <span>
                  {Array.isArray(step.targets) && step.targets.length > 0
                    ? step.targets.join(" / ")
                    : typeof step.count === "number"
                      ? `${step.count} 个对象`
                      : step.action || "已解析"}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <div className="case-analysis-card__grid">
        {sectionGroups.map((group) => (
          <section className="case-analysis-card__section" key={group.title}>
            <div className="case-analysis-card__section-head">
              <h4>{group.title}</h4>
              <span>{group.items.length} 项</span>
            </div>
            {group.items.length > 0 ? (
              <div className="case-analysis-card__entry-list">
                {group.items.map((item, index) => {
                  const hints = collectEntryHints(item);
                  return (
                    <article
                      className="case-analysis-card__entry"
                      key={`${group.title}-${item.tag || index}`}
                    >
                      <div className="case-analysis-card__entry-head">
                        <strong>{item.tag || item.type || `节点 ${index + 1}`}</strong>
                        {item.category && <span>{item.category}</span>}
                      </div>
                      {hints.length > 0 && (
                        <ul className="case-analysis-card__entry-hints">
                          {hints.map((hint) => (
                            <li key={`${item.tag || index}-${hint}`}>{hint}</li>
                          ))}
                        </ul>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="case-analysis-card__empty">未解析到该部分。</p>
            )}
          </section>
        ))}
      </div>

      {designIntent.length > 0 && (
        <section className="case-analysis-card__section">
          <h4>为什么这样设计</h4>
          <ul className="case-analysis-card__bullet-list">
            {designIntent.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}

      {editWorkflow.length > 0 && (
        <section className="case-analysis-card__section">
          <h4>建议的副本修改顺序</h4>
          <ol className="case-analysis-card__bullet-list case-analysis-card__bullet-list--ordered">
            {editWorkflow.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </section>
      )}

      {caseData.context_block && (
        <section className="case-analysis-card__section">
          <h4>可复用上下文</h4>
          <pre className="case-analysis-card__context-block">
            {caseData.context_block}
          </pre>
        </section>
      )}

      {nodeTreeExcerpt.length > 0 && (
        <details className="case-analysis-card__tree">
          <summary>查看模型树摘录</summary>
          <pre className="case-analysis-card__context-block">
            {nodeTreeExcerpt.join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}
