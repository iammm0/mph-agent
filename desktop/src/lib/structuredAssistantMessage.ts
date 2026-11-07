/**
 * 将后端偶发返回的「整段 JSON 字符串」解析为适合气泡展示的文案与模型路径。
 * 例如：{"message":"研究配置成功","model_path":"C:\\...\\x.mph","success":true}
 */

export interface StructuredAssistantPayload {
  /** 展示用短文案 */
  text: string;
  /** 用于「打开目录 / 预览」等操作 */
  modelPath: string | null;
}

function pickString(obj: Record<string, unknown>, key: string): string | null {
  const v = obj[key];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

/**
 * 若 raw 为工具/执行结果形态的 JSON，则返回结构化字段；否则返回 null。
 */
export function parseStructuredAssistantText(raw: string): StructuredAssistantPayload | null {
  const s = raw.trim();
  if (!s.startsWith("{") || !s.endsWith("}")) return null;

  let obj: Record<string, unknown>;
  try {
    obj = JSON.parse(s) as Record<string, unknown>;
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;

  const modelPath =
    pickString(obj, "model_path") ?? pickString(obj, "saved_path");
  const messageStr = pickString(obj, "message") ?? "";

  const status = obj.status;
  const statusStr = typeof status === "string" ? status : "";
  const hasStatusFlag =
    typeof obj.success === "boolean" ||
    statusStr === "success" ||
    statusStr === "error" ||
    statusStr === "warning";

  // 避免把普通 JSON 对话误判为工具结果：至少要有执行态字段或路径
  const looksLikeExecPayload = modelPath !== null || hasStatusFlag;
  if (!looksLikeExecPayload) return null;
  if (!messageStr && !modelPath) return null;

  const text =
    messageStr ||
    (modelPath ? `求解成功。模型位置：${modelPath}` : "操作已完成");

  return { text, modelPath };
}
