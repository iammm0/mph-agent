/**
 * 解析 `do_doctor` 返回的多行文本（见 agent/run/actions.py），供环境诊断卡片展示。
 */

import type { AssistantPresentation } from "./types";

export interface DoctorReport {
  outcome: "pass" | "fail";
  backendStatusLine: string | null;
  errors: string[];
  warnings: string[];
  infos: string[];
}

/**
 * 若文本形态与当前后端 `do_doctor` 输出一致则返回结构化结果，否则返回 null。
 */
export function parseDoctorReportText(text: string): DoctorReport | null {
  const rawLines = text.split(/\r?\n/);
  let outcomeIndex = -1;
  let outcome: "pass" | "fail" | null = null;

  for (let i = 0; i < rawLines.length; i++) {
    const t = rawLines[i].trim();
    if (t === "环境检查通过") {
      outcome = "pass";
      outcomeIndex = i;
      break;
    }
    if (t === "环境检查失败") {
      outcome = "fail";
      outcomeIndex = i;
      break;
    }
  }

  if (outcomeIndex < 0 || !outcome) return null;

  const headerLines = rawLines.slice(0, outcomeIndex);
  const tailLines = rawLines.slice(outcomeIndex + 1);

  const errors: string[] = [];
  const warnings: string[] = [];
  const infos: string[] = [];

  for (const line of tailLines) {
    const errM = line.match(/^\s*错误:\s*(.+)$/);
    if (errM) {
      errors.push(errM[1].trim());
      continue;
    }
    const warnM = line.match(/^\s*警告:\s*(.+)$/);
    if (warnM) {
      warnings.push(warnM[1].trim());
      continue;
    }
    const trimmed = line.trim();
    if (trimmed) infos.push(trimmed);
  }

  let backendStatusLine: string | null = null;
  for (const line of headerLines) {
    const t = line.trim();
    if (t.startsWith("各后端配置状态")) {
      backendStatusLine = t;
      break;
    }
  }

  return {
    outcome,
    backendStatusLine,
    errors,
    warnings,
    infos,
  };
}

/** 是否应以「环境诊断」富组件展示（显式标记或文本可解析）。 */
export function isEnvironmentDiagnosisMessage(
  text: string,
  presentation?: AssistantPresentation
): boolean {
  if (presentation === "environment_diagnosis") return true;
  return parseDoctorReportText(text) !== null;
}
