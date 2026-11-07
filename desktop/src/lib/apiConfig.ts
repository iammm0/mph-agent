const STORAGE_KEY = "mph-agent-api-config";
const LEGACY_STORAGE_KEY = "comsol-agent-api-config";
export const API_CONFIG_UPDATED_EVENT = "mph-agent-api-config-updated";

/** 桌面端当前仅开放 DeepSeek */
export type RuntimeBackendId = "deepseek";
export type LLMBackendId = "deepseek";

export interface ProviderConfig {
  api_key: string;
  base_url: string;
  model: string;
}

/** 跑任务前的计算偏好：自动 / 仅 CPU / 优先 GPU */
export type ComputePreference = "auto" | "cpu" | "gpu";

export interface ApiConfig {
  preferred_backend: LLMBackendId | null;
  providers: Record<LLMBackendId, ProviderConfig>;
  comsol_jar_path: string;
  /** Java 8 或 11 安装目录（JAVA_HOME），留空使用内置或系统 Java */
  java_home: string;
  /** COMSOL 求解计算偏好 */
  compute_preference: ComputePreference;
}

export interface ProviderCatalogEntry {
  id: LLMBackendId;
  label: string;
  shortLabel?: string;
  description: string;
  runtimeBackend: RuntimeBackendId;
  defaultBaseUrl: string;
  defaultModel: string;
  requiresApiKey: boolean;
  supportsBaseUrl: boolean;
  baseUrlLabel?: string;
  group: "china-direct";
}

export interface ContextWindowInfo {
  providerId: LLMBackendId | null;
  providerLabel: string;
  model: string;
  maxTokens: number;
  source: "model-pattern" | "provider-default" | "fallback";
}

type RawApiConfig = Partial<ApiConfig> &
  Record<string, unknown> & {
    preferred_backend?: string | null;
  };

export const PROVIDER_CATALOG: ProviderCatalogEntry[] = [
  {
    id: "deepseek",
    label: "DeepSeek",
    description: "DeepSeek 官方接口。",
    runtimeBackend: "deepseek",
    defaultBaseUrl: "",
    defaultModel: "deepseek-flash",
    requiresApiKey: true,
    supportsBaseUrl: false,
    group: "china-direct",
  },
];

const PROVIDER_ID_SET = new Set<string>(
  PROVIDER_CATALOG.map((provider) => provider.id)
);

const DEFAULT_CONTEXT_WINDOW_TOKENS = 65536;

const PROVIDER_CONTEXT_WINDOW_FALLBACKS: Record<LLMBackendId, number> = {
  deepseek: 65536,
};

function makeDefaultProviderConfig(
  provider: ProviderCatalogEntry
): ProviderConfig {
  return {
    api_key: "",
    base_url: provider.defaultBaseUrl,
    model: provider.defaultModel,
  };
}

function makeDefaultProviders(): Record<LLMBackendId, ProviderConfig> {
  return PROVIDER_CATALOG.reduce((acc, provider) => {
    acc[provider.id] = makeDefaultProviderConfig(provider);
    return acc;
  }, {} as Record<LLMBackendId, ProviderConfig>);
}

function makeDefaultConfig(): ApiConfig {
  return {
    preferred_backend: "deepseek",
    providers: makeDefaultProviders(),
    comsol_jar_path: "",
    java_home: "",
    compute_preference: "auto",
  };
}

export function normalizeComputePreference(value: unknown): ComputePreference {
  const v = String(value ?? "auto").trim().toLowerCase();
  if (v === "cpu" || v === "gpu" || v === "auto") return v;
  return "auto";
}

export const COMPUTE_PREFERENCE_OPTIONS: {
  id: ComputePreference;
  label: string;
  hint: string;
}[] = [
  {
    id: "auto",
    label: "自动",
    hint: "有 GPU 则尝试；不支持的物理场回落 CPU",
  },
  {
    id: "cpu",
    label: "仅 CPU",
    hint: "强制 CPU 多核，不尝试 GPU",
  },
  {
    id: "gpu",
    label: "优先 GPU",
    hint: "优先尝试 HardwareAcceleration（6.3 仅部分场景有效）",
  },
];

export function nextComputePreference(
  current: ComputePreference
): ComputePreference {
  const order: ComputePreference[] = ["auto", "cpu", "gpu"];
  const idx = order.indexOf(current);
  return order[(idx + 1) % order.length];
}

/** DeepSeek 已下线 deepseek-chat / deepseek-reasoner，映射到当前可用模型 */
const LEGACY_DEEPSEEK_MODELS: Record<string, string> = {
  "deepseek-chat": "deepseek-flash",
  "deepseek-reasoner": "deepseek-flash",
  "deepseek-v4-flash": "deepseek-flash",
  "deepseek-v4-flash-vision-exp": "deepseek-flash",
};

function normalizeDeepSeekModel(model: string): string {
  const trimmed = model.trim();
  return LEGACY_DEEPSEEK_MODELS[trimmed] ?? trimmed;
}

function mergeProviderConfig(
  provider: ProviderCatalogEntry,
  raw?: Partial<ProviderConfig>
): ProviderConfig {
  const defaults = makeDefaultProviderConfig(provider);
  const modelRaw =
    typeof raw?.model === "string" ? raw.model : defaults.model;
  return {
    api_key: typeof raw?.api_key === "string" ? raw.api_key : defaults.api_key,
    base_url:
      typeof raw?.base_url === "string" ? raw.base_url : defaults.base_url,
    model:
      provider.id === "deepseek"
        ? normalizeDeepSeekModel(modelRaw)
        : modelRaw,
  };
}

/** 避免 { ...a, ...{ k: undefined } } 覆盖掉已有字符串配置 */
function definedProviderPartial(
  partial: Partial<ProviderConfig>
): Partial<ProviderConfig> {
  const out: Partial<ProviderConfig> = {};
  if (typeof partial.api_key === "string") out.api_key = partial.api_key;
  if (typeof partial.base_url === "string") out.base_url = partial.base_url;
  if (typeof partial.model === "string") out.model = partial.model;
  return out;
}

function mergeStoredConfig(raw: RawApiConfig): ApiConfig {
  const config = makeDefaultConfig();
  // UI 仅支持 DeepSeek：无论旧配置选了什么，都收敛到 deepseek
  config.preferred_backend = "deepseek";

  if (raw.providers && typeof raw.providers === "object") {
    const rawProviders = raw.providers as Record<string, Partial<ProviderConfig>>;
    config.providers.deepseek = mergeProviderConfig(
      getProviderMeta("deepseek"),
      rawProviders.deepseek
    );
  }

  const legacyDeepseek = definedProviderPartial({
    api_key:
      typeof raw.deepseek_api_key === "string" ? raw.deepseek_api_key : undefined,
    model:
      typeof raw.deepseek_model === "string" ? raw.deepseek_model : undefined,
  });
  if (Object.keys(legacyDeepseek).length > 0) {
    config.providers.deepseek = mergeProviderConfig(getProviderMeta("deepseek"), {
      ...config.providers.deepseek,
      ...legacyDeepseek,
    });
  }

  if (typeof raw.comsol_jar_path === "string") {
    config.comsol_jar_path = raw.comsol_jar_path;
  }
  if (typeof raw.java_home === "string") {
    config.java_home = raw.java_home;
  }
  if (
    typeof raw.compute_preference === "string" ||
    typeof (raw as { COMSOL_COMPUTE_PREFERENCE?: string }).COMSOL_COMPUTE_PREFERENCE ===
      "string"
  ) {
    config.compute_preference = normalizeComputePreference(
      raw.compute_preference ??
        (raw as { COMSOL_COMPUTE_PREFERENCE?: string }).COMSOL_COMPUTE_PREFERENCE
    );
  }

  return config;
}

export function getProviderCatalog(): ProviderCatalogEntry[] {
  return PROVIDER_CATALOG.map((provider) => ({ ...provider }));
}

export function isProviderId(value: unknown): value is LLMBackendId {
  return typeof value === "string" && PROVIDER_ID_SET.has(value);
}

export function getProviderMeta(providerId: LLMBackendId): ProviderCatalogEntry {
  const provider = PROVIDER_CATALOG.find((item) => item.id === providerId);
  if (!provider) {
    throw new Error(`Unknown LLM provider: ${providerId}`);
  }
  return provider;
}

export function getProviderLabel(providerId: string | null | undefined): string {
  if (!isProviderId(providerId)) return "DeepSeek";
  return getProviderMeta(providerId).shortLabel ?? getProviderMeta(providerId).label;
}

export function getProviderConfig(
  config: ApiConfig,
  providerId: LLMBackendId
): ProviderConfig {
  return mergeProviderConfig(
    getProviderMeta(providerId),
    config.providers?.[providerId]
  );
}

export function resolveSelectedProviderId(
  config: ApiConfig,
  backend?: LLMBackendId | null
): LLMBackendId | null {
  if (isProviderId(backend)) return backend;
  return config.preferred_backend && isProviderId(config.preferred_backend)
    ? config.preferred_backend
    : "deepseek";
}

function inferModelContextWindow(
  model: string,
  fallback: number
): Pick<ContextWindowInfo, "maxTokens" | "source"> {
  const normalized = model.trim().toLowerCase();
  if (!normalized) {
    return { maxTokens: fallback, source: "fallback" };
  }

  const sizeMatches: Array<[RegExp, number]> = [
    [/(^|[^0-9])128k([^0-9]|$)/, 128000],
    [/(^|[^0-9])64k([^0-9]|$)/, 65536],
    [/(^|[^0-9])32k([^0-9]|$)/, 32768],
    [/(^|[^0-9])16k([^0-9]|$)/, 16384],
    [/(^|[^0-9])8k([^0-9]|$)/, 8192],
  ];
  for (const [pattern, maxTokens] of sizeMatches) {
    if (pattern.test(normalized)) {
      return { maxTokens, source: "model-pattern" };
    }
  }

  if (normalized.includes("deepseek")) {
    return { maxTokens: fallback, source: "provider-default" };
  }

  return { maxTokens: fallback, source: "provider-default" };
}

export function getContextWindowInfo(
  config: ApiConfig,
  backend?: LLMBackendId | null
): ContextWindowInfo {
  const providerId = resolveSelectedProviderId(config, backend) ?? "deepseek";
  const provider = getProviderConfig(config, providerId);
  const fallback =
    PROVIDER_CONTEXT_WINDOW_FALLBACKS[providerId] ?? DEFAULT_CONTEXT_WINDOW_TOKENS;
  const inferred = inferModelContextWindow(provider.model, fallback);

  return {
    providerId,
    providerLabel: getProviderLabel(providerId),
    model: provider.model,
    maxTokens: inferred.maxTokens,
    source: inferred.source,
  };
}

export function resolveRuntimeBackend(
  providerId: LLMBackendId
): RuntimeBackendId {
  return getProviderMeta(providerId).runtimeBackend;
}

export function loadApiConfig(): ApiConfig {
  try {
    let raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      raw = localStorage.getItem(LEGACY_STORAGE_KEY);
      if (raw) {
        localStorage.removeItem(LEGACY_STORAGE_KEY);
      }
    }
    if (raw) {
      const parsed = JSON.parse(raw) as RawApiConfig;
      const config = mergeStoredConfig(parsed);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
      return config;
    }
  } catch (_) {}
  return makeDefaultConfig();
}

export function saveApiConfig(config: ApiConfig): void {
  try {
    const merged = mergeStoredConfig(config as unknown as RawApiConfig);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
    window.dispatchEvent(
      new CustomEvent(API_CONFIG_UPDATED_EVENT, {
        detail: { preferredBackend: merged.preferred_backend ?? null },
      })
    );
  } catch (_) {}
}

/** 转为 .env 风格的 LLM 键值对，供后端 config_save 使用 */
export function apiConfigToEnv(config: ApiConfig): Record<string, string> {
  const env: Record<string, string> = {
    LLM_BACKEND: "deepseek",
    DEEPSEEK_API_KEY: "",
    DEEPSEEK_MODEL: "",
    COMSOL_COMPUTE_PREFERENCE: normalizeComputePreference(
      config.compute_preference
    ),
  };

  const provider = getProviderConfig(config, "deepseek");
  env.DEEPSEEK_API_KEY = provider.api_key;
  env.DEEPSEEK_MODEL = provider.model;
  return env;
}

/** 根据当前提供商从 config 中取出 API payload */
export function getPayloadFromConfig(
  backend: string | null,
  config: ApiConfig
): Record<string, unknown> {
  const providerId = resolveSelectedProviderId(
    config,
    isProviderId(backend) ? backend : null
  );
  if (!providerId) return {};

  const provider = getProviderConfig(config, providerId);
  const payload: Record<string, unknown> = { backend: "deepseek" };
  if (provider.api_key) payload.api_key = provider.api_key;
  if (provider.model) payload.model = provider.model;
  return payload;
}
