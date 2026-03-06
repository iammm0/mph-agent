const STORAGE_KEY = "mph-agent-api-config";
const LEGACY_STORAGE_KEY = "comsol-agent-api-config";

export type LLMBackendId = "deepseek" | "kimi" | "ollama" | "openai-compatible";

export interface ApiConfig {
  preferred_backend: LLMBackendId | null;
  deepseek_api_key: string;
  deepseek_model: string;
  kimi_api_key: string;
  kimi_model: string;
  openai_compatible_base_url: string;
  openai_compatible_api_key: string;
  openai_compatible_model: string;
  ollama_url: string;
  ollama_model: string;
  comsol_jar_path: string;
  /** Java 8 或 11 安装目录（JAVA_HOME），留空使用内置或系统 Java */
  java_home: string;
}

const defaultConfig: ApiConfig = {
  preferred_backend: null,
  deepseek_api_key: "",
  deepseek_model: "deepseek-reasoner",
  kimi_api_key: "",
  kimi_model: "moonshot-v1-8k",
  openai_compatible_base_url: "",
  openai_compatible_api_key: "",
  openai_compatible_model: "gpt-3.5-turbo",
  ollama_url: "http://localhost:11434",
  ollama_model: "llama3",
  comsol_jar_path: "",
  java_home: "",
};

export function loadApiConfig(): ApiConfig {
  try {
    let raw = localStorage.getItem(STORAGE_KEY);
    if (!raw && LEGACY_STORAGE_KEY) {
      raw = localStorage.getItem(LEGACY_STORAGE_KEY);
      if (raw) {
        localStorage.setItem(STORAGE_KEY, raw);
        localStorage.removeItem(LEGACY_STORAGE_KEY);
      }
    }
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ApiConfig>;
      return { ...defaultConfig, ...parsed };
    }
  } catch (_) {}
  return { ...defaultConfig };
}

export function saveApiConfig(config: ApiConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch (_) {}
}

/** 转为 .env 风格的键值对，供后端 config_save 使用 */
export function apiConfigToEnv(config: ApiConfig): Record<string, string> {
  const env: Record<string, string> = {};
  if (config.preferred_backend) env.LLM_BACKEND = config.preferred_backend;
  if (config.deepseek_api_key) env.DEEPSEEK_API_KEY = config.deepseek_api_key;
  if (config.deepseek_model) env.DEEPSEEK_MODEL = config.deepseek_model;
  if (config.kimi_api_key) env.KIMI_API_KEY = config.kimi_api_key;
  if (config.kimi_model) env.KIMI_MODEL = config.kimi_model;
  if (config.openai_compatible_base_url)
    env.OPENAI_COMPATIBLE_BASE_URL = config.openai_compatible_base_url;
  if (config.openai_compatible_api_key)
    env.OPENAI_COMPATIBLE_API_KEY = config.openai_compatible_api_key;
  if (config.openai_compatible_model)
    env.OPENAI_COMPATIBLE_MODEL = config.openai_compatible_model;
  if (config.ollama_url) env.OLLAMA_URL = config.ollama_url;
  if (config.ollama_model) env.OLLAMA_MODEL = config.ollama_model;
  if (config.comsol_jar_path) env.COMSOL_JAR_PATH = config.comsol_jar_path;
  if (config.java_home) env.JAVA_HOME = config.java_home;
  return env;
}

/** 根据当前后端从 config 中取出 API 相关 payload，供 run/plan 请求使用 */
export function getPayloadFromConfig(
  backend: string | null,
  config: ApiConfig
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  switch (backend) {
    case "deepseek":
      if (config.deepseek_api_key) payload.api_key = config.deepseek_api_key;
      if (config.deepseek_model) payload.model = config.deepseek_model;
      break;
    case "kimi":
      if (config.kimi_api_key) payload.api_key = config.kimi_api_key;
      if (config.kimi_model) payload.model = config.kimi_model;
      break;
    case "openai-compatible":
      if (config.openai_compatible_base_url)
        payload.base_url = config.openai_compatible_base_url;
      if (config.openai_compatible_api_key)
        payload.api_key = config.openai_compatible_api_key;
      if (config.openai_compatible_model)
        payload.model = config.openai_compatible_model;
      break;
    case "ollama":
      if (config.ollama_url) payload.ollama_url = config.ollama_url;
      if (config.ollama_model) payload.model = config.ollama_model;
      break;
    default:
      break;
  }
  return payload;
}
