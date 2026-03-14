import { useState } from "react";
import { useAppState } from "../../context/AppStateContext";
import { useBridge } from "../../hooks/useBridge";
import type {
  ClarifyingAnswer,
  ClarifyingQuestion,
  ClarifyingOption,
} from "../../lib/types";

interface PlanQuestionsDialogProps {
  onClose: () => void;
}

export function PlanQuestionsDialog({ onClose }: PlanQuestionsDialogProps) {
  const { state, dispatch } = useAppState();
  const { sendStreamCommand } = useBridge();
  const questions: ClarifyingQuestion[] = state.pendingPlanQuestions ?? [];
  const [answers, setAnswers] = useState<Record<string, string[]>>({});

  const toggleOption = (q: ClarifyingQuestion, optionId: string) => {
    setAnswers((prev) => {
      const current = prev[q.id] ?? [];
      if (q.type === "single") {
        return { ...prev, [q.id]: [optionId] };
      }
      if (current.includes(optionId)) {
        return { ...prev, [q.id]: current.filter((id) => id !== optionId) };
      }
      return { ...prev, [q.id]: [...current, optionId] };
    });
  };

  const handleConfirm = () => {
    const input = state.lastPlanInput;
    if (!input) {
      onClose();
      return;
    }
    const payloadAnswers: ClarifyingAnswer[] = questions.map((q: ClarifyingQuestion) => ({
      questionId: q.id,
      selectedOptionIds: answers[q.id] ?? [],
    }));
    // 使用与首次 /run 相同的 API payload（由 useBridge 内部处理 backend 配置）
    sendStreamCommand("run", {
      input,
      clarifying_answers: payloadAnswers,
    });
    dispatch({ type: "CLEAR_PLAN_QUESTIONS" });
    dispatch({ type: "SET_DIALOG", dialog: null });
    onClose();
  };

  const handleCancel = () => {
    dispatch({ type: "CLEAR_PLAN_QUESTIONS" });
    dispatch({ type: "SET_DIALOG", dialog: null });
    onClose();
  };

  return (
    <div className="dialog plan-questions-dialog">
      <div className="dialog-header">
        <h2>在执行前先澄清几个问题</h2>
      </div>
      <div className="dialog-body">
        {questions.length === 0 ? (
          <p>当前计划未包含需要澄清的问题。</p>
        ) : (
          <div className="plan-questions-list">
            {questions.map((q: ClarifyingQuestion) => (
              <div key={q.id} className="plan-question-item">
                <div className="plan-question-text">{q.text}</div>
                <div className="plan-question-options">
                  {q.options.map((opt: ClarifyingOption) => {
                    const selected = (answers[q.id] ?? []).includes(opt.id);
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        className={`plan-question-option ${selected ? "selected" : ""}`}
                        onClick={() => toggleOption(q, opt.id)}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="dialog-footer">
        <button type="button" className="btn" onClick={handleCancel}>
          取消
        </button>
        <button
          type="button"
          className="btn primary"
          onClick={handleConfirm}
          disabled={questions.length === 0}
        >
          确认并继续执行
        </button>
      </div>
    </div>
  );
}

