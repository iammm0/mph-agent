import { useEffect, useMemo, useState } from "react";
import { useAppState } from "../../context/AppStateContext";
import { useBridge } from "../../hooks/useBridge";
import { getPayloadFromConfig, loadApiConfig } from "../../lib/apiConfig";
import type { ClarifyingAnswer, ClarifyingQuestion } from "../../lib/types";
import {
  normalizeClarifyingQuestions,
  isMultiSelectQuestion,
  SUPPLEMENT_OPTION_ID,
} from "../../lib/clarifying";
import { ClarifyingQuestionItem } from "../clarifying";

interface PlanQuestionsDialogProps {
  onClose: () => void;
}

type AnswerState = Record<string, string[]>;
type SupplementTextState = Record<string, string>;

function ensureSelected(
  current: string[],
  optionId: string,
  checked: boolean,
): string[] {
  if (checked) {
    return current.includes(optionId) ? current : [...current, optionId];
  }
  return current.filter((id) => id !== optionId);
}

export function PlanQuestionsDialog({ onClose }: PlanQuestionsDialogProps) {
  const { state, dispatch } = useAppState();
  const { sendStreamCommand } = useBridge();

  const questions: ClarifyingQuestion[] = useMemo(
    () => normalizeClarifyingQuestions(state.pendingPlanQuestions ?? []),
    [state.pendingPlanQuestions],
  );

  const [answers, setAnswers] = useState<AnswerState>({});
  const [supplements, setSupplements] = useState<SupplementTextState>({});

  useEffect(() => {
    if (questions.length === 0) return;
    setAnswers((prev) => {
      const next = { ...prev };
      let changed = false;
      questions.forEach((q) => {
        if (next[q.id]?.length) return;
        const recommended = q.options.find((o) => o.recommended);
        if (recommended) {
          next[q.id] = [recommended.id];
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [questions]);

  const handleToggleOption = (questionId: string, optionId: string) => {
    const question = questions.find((item) => item.id === questionId);
    if (!question) return;

    setAnswers((prev) => {
      const current = prev[questionId] ?? [];
      if (!isMultiSelectQuestion(question)) {
        return { ...prev, [questionId]: [optionId] };
      }
      const selected = current.includes(optionId);
      return {
        ...prev,
        [questionId]: ensureSelected(current, optionId, !selected),
      };
    });
  };

  const handleChangeSupplement = (questionId: string, value: string) => {
    setSupplements((prev) => ({ ...prev, [questionId]: value }));
  };

  const answeredCount = useMemo(() => {
    return questions.filter((q) => {
      const selected = answers[q.id] ?? [];
      if (selected.length === 0) return false;
      if (!selected.includes(SUPPLEMENT_OPTION_ID)) return true;
      return (supplements[q.id] ?? "").trim().length > 0;
    }).length;
  }, [questions, answers, supplements]);

  const canConfirm = useMemo(() => {
    if (questions.length === 0) return false;

    return questions.every((q) => {
      const selected = answers[q.id] ?? [];
      if (selected.length === 0) return false;

      const selectedSupplement = selected.includes(SUPPLEMENT_OPTION_ID);
      if (!selectedSupplement) return true;

      return (supplements[q.id] ?? "").trim().length > 0;
    });
  }, [questions, answers, supplements]);

  const buildPayloadAnswers = (): ClarifyingAnswer[] => {
    return questions.map((q) => {
      const selected_option_ids = answers[q.id] ?? [];
      const supplement_text = (supplements[q.id] ?? "").trim();

      const base: ClarifyingAnswer = {
        question_id: q.id,
        selected_option_ids,
      };

      if (supplement_text) {
        base.supplement_text = supplement_text;
      }

      return base;
    });
  };

  const handleConfirm = () => {
    const input = state.lastPlanInput;
    if (!input) {
      onClose();
      return;
    }

    const payloadAnswers = buildPayloadAnswers();
    const apiPayload = getPayloadFromConfig(state.backend, loadApiConfig());

    void sendStreamCommand("chat", {
      input,
      clarifying_answers: payloadAnswers,
      output: state.outputDefault ?? undefined,
      workspace_dir: state.workspaceDir ?? undefined,
      ...apiPayload,
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

  const continueLabel = "确认答案并继续";
  const helperText =
    questions.length > 0
      ? `已完成 ${answeredCount}/${questions.length} 个澄清项。回答完后点击右下角继续。`
      : "当前计划未包含需要澄清的问题。";

  return (
    <div className="dialog plan-questions-dialog">
      <div className="dialog-header">
        <h2>继续前先澄清几个问题</h2>
      </div>

      <div className="dialog-body">
        <p className="plan-questions-intro">{helperText}</p>
        {questions.length === 0 ? (
          <p className="plan-questions-empty">当前计划未包含需要澄清的问题。</p>
        ) : (
          <div className="plan-questions-list">
            {questions.map((q) => (
              <ClarifyingQuestionItem
                key={q.id}
                question={q}
                selectedOptionIds={answers[q.id] ?? []}
                supplementText={supplements[q.id] ?? ""}
                onToggleOption={handleToggleOption}
                onChangeSupplement={handleChangeSupplement}
              />
            ))}
          </div>
        )}
      </div>

      <div className="dialog-actions plan-questions-actions">
        <div className="plan-questions-actions-status">
          {questions.length > 0
            ? canConfirm
              ? "澄清答案已齐全，可以继续。"
              : "还有未回答的问题。"
            : "没有待处理的澄清项。"}
        </div>
        <div className="plan-questions-actions-buttons">
          <button
            type="button"
            className="dialog-btn secondary"
            onClick={handleCancel}
          >
            取消
          </button>
          <button
            type="button"
            className="dialog-btn primary"
            onClick={handleConfirm}
            disabled={!canConfirm}
            title={continueLabel}
          >
            {continueLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
