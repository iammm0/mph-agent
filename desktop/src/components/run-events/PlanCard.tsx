import type { RunEvent } from "../../lib/types";
import { Icon } from "../Icon";
import { normalizeClarifyingQuestions } from "../../lib/clarifying";

/** 规划开始：仅提示已进入规划，不重复展示用户输入全文 */
export function PlanStartCard({ event: _event }: { event: RunEvent }) {
  return (
    <div className="run-event-card run-event-card--plan-start">
      <span className="run-event-card__icon" aria-hidden>
        <Icon name="task-square" size={16} />
      </span>
      <div className="run-event-card__main">
        <span className="run-event-card__title">规划开始</span>
        <p className="run-event-card__plan-start-hint">已收到您的建模需求，正在拆解任务...</p>
      </div>
    </div>
  );
}

/** 规划完成：展示模型名与步骤链 */
export function PlanEndCard({ event }: { event: RunEvent }) {
  const d = event.data ?? {};
  const steps = d.steps as Array<{
    action?: string;
    step_type?: string;
    label?: string;
    why?: string;
    inputs?: string[];
  }> | undefined;
  const model = String(d.model_name ?? "").trim();
  const desc = d.plan_description as string | undefined;
  const structuredQuestions = normalizeClarifyingQuestions(d.clarifying_questions);
  const questions =
    structuredQuestions.length > 0
      ? structuredQuestions.map((q) => q.text)
      : Array.isArray(d.clarifying_questions)
        ? (d.clarifying_questions as Array<unknown>)
            .map((q) => {
              if (q && typeof q === "object") {
                const obj = q as Record<string, unknown>;
                return String(obj.text ?? "").trim();
              }
              return String(q ?? "").trim();
            })
            .filter((q) => q && !/^(问题|question)\s*\d+$/i.test(q))
        : [];
  const cases = Array.isArray(d.case_library_suggestions)
    ? (d.case_library_suggestions as Array<unknown>)
        .map((item) => {
          if (item && typeof item === "object") {
            const obj = item as Record<string, unknown>;
            return {
              title: String(obj.title ?? "").trim(),
              url: String(obj.url ?? "").trim(),
              source: String(obj.source ?? "").trim(),
            };
          }
          return { title: String(item ?? "").trim(), url: "", source: "" };
        })
        .filter((entry) => entry.title || entry.url)
    : [];

  return (
    <div className="run-event-card run-event-card--plan-end">
      <span className="run-event-card__icon" aria-hidden>
        <Icon name="tick-circle" size={16} />
      </span>
      <div className="run-event-card__main">
        <span className="run-event-card__title">规划完成</span>
        {model && <p className="run-event-card__model">{model}</p>}
        {desc && (
          <div className="run-event-card__plan-rationale">
            <span className="run-event-card__kicker">推理思路</span>
            <p className="run-event-card__desc">{desc}</p>
          </div>
        )}
        {steps?.length ? (
          <ol className="run-event-card__steps run-event-card__steps--detailed">
            {steps.map((s, i) => (
              <li key={i}>
                <strong>{s.label ?? s.action ?? s.step_type ?? "步骤"}</strong>
                {s.why ? <p className="run-event-card__step-why">{s.why}</p> : null}
                {Array.isArray(s.inputs) && s.inputs.length > 0 ? (
                  <ul className="run-event-card__step-inputs">
                    {s.inputs.map((input, j) => (
                      <li key={j}>{input}</li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ol>
        ) : null}
        {questions.length ? (
          <>
            <p className="run-event-card__detail">需要澄清</p>
            <ul className="run-event-card__list">
              {questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </>
        ) : null}
        {cases.length ? (
          <>
            <p className="run-event-card__detail">案例库参考</p>
            <ul className="run-event-card__list">
              {cases.map((item, i) => (
                <li key={i}>
                  {item.title || "案例"}
                  {item.url ? ` - ${item.url}` : ""}
                  {item.source ? ` (${item.source})` : ""}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </div>
  );
}
