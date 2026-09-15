const STORAGE_KEY = "mph-agent-api-config";
const LEGACY_STORAGE_KEY = "comsol-agent-api-config";
export const API_CONFIG_UPDATED_EVENT = "mph-agent-api-config-updated";

export type RuntimeBackendId =
  | "deepseek"
  | "kimi"
  | "ollama"
  | "openai-compatible";

export type LLMBackendId =
  | "deepseek"
  | "kimi"
  | "openai"
  | "anthropic"
  | "gemini"
  | "xai"
  | "qwen"
  | "zhipu"
  | "openrouter"
  | "groq"
  | "together"
  | "fireworks"
  | "siliconflow"
  | "perplexity"
  | "mistral"
  | "volcengine-ark"
  | "azure-openai"
  | "custom-openai"
  | "ollama";

export interface ProviderConfig {
  api_key: string;
  base_url: string;
  model: string;
}

export interface ApiConfig {
  preferred_backend: LLMBackendId | null;
  providers: Record<LLMBackendId, ProviderConfig>;
  comsol_jar_path: string;
  /** Java 8 或 11 安装目录（JAVA_HOME），留空使用内置或系统 Java */
  java_home: string;
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
  /** 设置页分区：国内直连 / 海外兼容 / 企业或自定义网关 / 本地 */
  group: "china-direct" | "overseas-relay" | "custom-gateway" | "local";
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
    description: "DeepSeek 官方接口，Python 运行时内置直连。",
    runtimeBackend: "deepseek",
    defaultBaseUrl: "",
    defaultModel: "deepseek-reasoner",
    requiresApiKey: true,
    supportsBaseUrl: false,
    group: "china-direct",
  },
  {
    id: "kimi",
    label: "Kimi / Moonshot",
    shortLabel: "Kimi",
    description: "Moonshot Kimi 官方接口，Python 运行时内置直连。",
    runtimeBackend: "kimi",
    defaultBaseUrl: "",
    defaultModel: "moonshot-v1-8k",
    requiresApiKey: true,
    supportsBaseUrl: false,
    group: "china-direct",
  },
  {
    id: "openai",
    label: "OpenAI",
    description: "OpenAI 官方 API，按 OpenAI-compatible 运行时发送。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4.1-mini",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    shortLabel: "Claude",
    description: "Anthropic OpenAI SDK 兼容层，适合接入 Claude 系列模型。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.anthropic.com/v1/",
    defaultModel: "claude-sonnet-4-5-20250929",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    shortLabel: "Gemini",
    description: "Google Gemini OpenAI 兼容接口。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    defaultModel: "gemini-2.5-flash",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "xai",
    label: "xAI Grok",
    shortLabel: "xAI",
    description: "xAI 官方 OpenAI 兼容接口。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.x.ai/v1",
    defaultModel: "grok-4-latest",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "qwen",
    label: "通义千问 / DashScope",
    shortLabel: "Qwen",
    description: "阿里云百炼 DashScope OpenAI 兼容模式。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    defaultModel: "qwen-plus",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "china-direct",
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    shortLabel: "GLM",
    description: "智谱 BigModel OpenAI 兼容接口。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://open.bigmodel.cn/api/paas/v4/",
    defaultModel: "glm-4-plus",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "china-direct",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    description: "多模型聚合网关，使用 OpenAI 兼容协议。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "openai/gpt-4.1-mini",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "groq",
    label: "Groq",
    description: "GroqCloud OpenAI 兼容接口，适合高速推理模型。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.groq.com/openai/v1",
    defaultModel: "openai/gpt-oss-20b",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "together",
    label: "Together AI",
    description: "Together AI OpenAI 兼容接口。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.together.xyz/v1",
    defaultModel: "openai/gpt-oss-20b",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "fireworks",
    label: "Fireworks AI",
    description: "Fireworks 推理 API，使用 OpenAI 兼容协议。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.fireworks.ai/inference/v1",
    defaultModel: "accounts/fireworks/models/llama-v3p1-8b-instruct",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "siliconflow",
    label: "SiliconFlow",
    description: "硅基流动 OpenAI 兼容接口。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.siliconflow.cn/v1",
    defaultModel: "Qwen/Qwen3-32B",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "china-direct",
  },
  {
    id: "perplexity",
    label: "Perplexity",
    description: "Perplexity Sonar API，使用 OpenAI 兼容协议。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.perplexity.ai",
    defaultModel: "sonar",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "mistral",
    label: "Mistral AI",
    description: "Mistral 官方 API，使用 OpenAI 兼容协议。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://api.mistral.ai/v1",
    defaultModel: "mistral-small-latest",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "overseas-relay",
  },
  {
    id: "volcengine-ark",
    label: "火山方舟 Ark",
    shortLabel: "Ark",
    description: "火山引擎 Ark OpenAI 兼容接口，模型名通常填写方舟 endpoint/model ID。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-seed-1-6-251015",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "china-direct",
  },
  {
    id: "azure-openai",
    label: "Azure OpenAI",
    shortLabel: "Azure",
    description: "Azure OpenAI v1 兼容接口；Base URL 需要替换为你的 Azure 资源地址。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl:
      "https://YOUR-RESOURCE.openai.azure.com/openai/v1",
    defaultModel: "gpt-4.1-mini",
    requiresApiKey: true,
    supportsBaseUrl: true,
    baseUrlLabel: "Azure Base URL",
    group: "custom-gateway",
  },
  {
    id: "custom-openai",
    label: "自定义 OpenAI 兼容",
    shortLabel: "自定义兼容",
    description: "任意兼容 /v1/chat/completions 的中转、私有网关或企业代理。",
    runtimeBackend: "openai-compatible",
    defaultBaseUrl: "",
    defaultModel: "gpt-4o-mini",
    requiresApiKey: true,
    supportsBaseUrl: true,
    group: "custom-gateway",
  },
  {
    id: "ollama",
    label: "Ollama",
    description: "本地或远程 Ollama 服务，不需要 API Key。",
    runtimeBackend: "ollama",
    defaultBaseUrl: "http://localhost:11434",
    defaultModel: "llama3",
    requiresApiKey: false,
    supportsBaseUrl: true,
    baseUrlLabel: "Ollama 地址",
    group: "local",
  },
];

const PROVIDER_ID_SET = new Set<string>(
  PROVIDER_CATALOG.map((provider) => provider.id)
);

const DEFAULT_CONTEXT_WINDOW_TOKENS = 131072;

const PROVIDER_CONTEXT_WINDOW_FALLBACKS: Record<LLMBackendId, number> = {
  deepseek: 65536,
  kimi: 131072,
  openai: 1000000,
  anthropic: 200000,
  gemini: 1000000,
  xai: 256000,
  qwen: 131072,
  zhipu: 128000,
  openrouter: 200000,
  groq: 131072,
  together: 131072,
  fireworks: 131072,
  siliconflow: 131072,
  perplexity: 128000,
  mistral: 128000,
  "volcengine-ark": 256000,
  "azure-openai": 1000000,
  "custom-openai": 128000,
  ollama: 8192,
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
    preferred_backend: null,
    providers: makeDefaultProviders(),
    comsol_jar_path: "",
    java_home: "",
  };
}

function mergeProviderConfig(
  provider: ProviderCatalogEntry,
  raw?: Partial<ProviderConfig>
): ProviderConfig {
  const defaults = makeDefaultProviderConfig(provider);
  return {
    api_key: typeof raw?.api_key === "string" ? raw.api_key : defaults.api_key,
    base_url:
      typeof raw?.base_url === "string" ? raw.base_url : defaults.base_url,
    model: typeof raw?.model === "string" ? raw.model : defaults.model,
  };
}

function normalizeUrl(value: string): string {
  return value.trim().replace(/\/+$/, "").toLowerCase();
}

function inferCompatibleProvider(baseUrl: string): LLMBackendId {
  const normalized = normalizeUrl(baseUrl);
  const match = PROVIDER_CATALOG.find(
    (provider) =>
      provider.runtimeBackend === "openai-compatible" &&
      provider.id !== "custom-openai" &&
      normalizeUrl(provider.defaultBaseUrl) === normalized
  );
  return match?.id ?? "custom-openai";
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
  const preferredBackend: string | null =
    typeof raw.preferred_backend === "string" ? raw.preferred_backend : null;

  if (preferredBackend && isProviderId(preferredBackend)) {
    config.preferred_backend = preferredBackend;
  } else if (preferredBackend === "openai-compatible") {
    const legacyBaseUrl =
      typeof raw.openai_compatible_base_url === "string"
        ? raw.openai_compatible_base_url
        : "";
    config.preferred_backend = inferCompatibleProvider(legacyBaseUrl);
  }

  if (raw.providers && typeof raw.providers === "object") {
    const rawProviders = raw.providers as Record<string, Partial<ProviderConfig>>;
    for (const provider of PROVIDER_CATALOG) {
      config.providers[provider.id] = mergeProviderConfig(
        provider,
        rawProviders[provider.id]
      );
    }
  }

  const legacyCompatibleId = inferCompatibleProvider(
    typeof raw.openai_compatible_base_url === "string"
      ? raw.openai_compatible_base_url
      : ""
  );

  const legacyProviderMap: Array<[LLMBackendId, Partial<ProviderConfig>]> = [
    [
      "deepseek",
      {
        api_key:
          typeof raw.deepseek_api_key === "string"
            ? raw.deepseek_api_key
            : undefined,
        model:
          typeof raw.deepseek_model === "string"
            ? raw.deepseek_model
            : undefined,
      },
    ],
    [
      "kimi",
      {
        api_key:
          typeof raw.kimi_api_key === "string" ? raw.kimi_api_key : undefined,
        model:
          typeof raw.kimi_model === "string" ? raw.kimi_model : undefined,
      },
    ],
    [
      legacyCompatibleId,
      {
        api_key:
          typeof raw.openai_compatible_api_key === "string"
            ? raw.openai_compatible_api_key
            : undefined,
        base_url:
          typeof raw.openai_compatible_base_url === "string"
            ? raw.openai_compatible_base_url
            : undefined,
        model:
          typeof raw.openai_compatible_model === "string"
            ? raw.openai_compatible_model
            : undefined,
      },
    ],
    [
      "ollama",
      {
        base_url:
          typeof raw.ollama_url === "string" ? raw.ollama_url : undefined,
        model:
          typeof raw.ollama_model === "string" ? raw.ollama_model : undefined,
      },
    ],
  ];

  for (const [providerId, partial] of legacyProviderMap) {
    const cleaned = definedProviderPartial(partial);
    if (Object.keys(cleaned).length === 0) continue;
    const provider = getProviderMeta(providerId);
    config.providers[providerId] = mergeProviderConfig(provider, {
      ...config.providers[providerId],
      ...cleaned,
    });
  }

  if (typeof raw.comsol_jar_path === "string") {
    config.comsol_jar_path = raw.comsol_jar_path;
  }
  if (typeof raw.java_home === "string") {
    config.java_home = raw.java_home;
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
  if (!isProviderId(providerId)) return "默认";
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
    : null;
}

function inferModelContextWindow(
  model: string,
  fallback: number
): Pick<ContextWindowInfo, "maxTokens" | "source"> {
  const normalized = model.trim().toLowerCase();
  if (!normalized) {
    return { maxTokens: fallback, source: "fallback" };
  }

  if (
    normalized.includes("gpt-4.1") ||
    normalized.includes("gpt-5") ||
    normalized.includes("gemini-2.5")
  ) {
    return { maxTokens: 1000000, source: "model-pattern" };
  }

  if (
    normalized.includes("claude") ||
    normalized.includes("openai/o1") ||
    normalized.includes("openai/o3") ||
    normalized.includes("openai/o4")
  ) {
    return { maxTokens: 200000, source: "model-pattern" };
  }

  if (normalized.includes("grok")) {
    return { maxTokens: 256000, source: "model-pattern" };
  }

  const sizeMatches: Array<[RegExp, number]> = [
    [/(^|[^0-9])1m([^0-9]|$)/, 1000000],
    [/(^|[^0-9])256k([^0-9]|$)/, 256000],
    [/(^|[^0-9])200k([^0-9]|$)/, 200000],
    [/(^|[^0-9])128k([^0-9]|$)/, 128000],
    [/(^|[^0-9])64k([^0-9]|$)/, 65536],
    [/(^|[^0-9])32k([^0-9]|$)/, 32768],
    [/(^|[^0-9])16k([^0-9]|$)/, 16384],
    [/(^|[^0-9])8k([^0-9]|$)/, 8192],
    [/(^|[^0-9])4k([^0-9]|$)/, 4096],
  ];
  for (const [pattern, maxTokens] of sizeMatches) {
    if (pattern.test(normalized)) {
      return { maxTokens, source: "model-pattern" };
    }
  }

  if (
    normalized.includes("deepseek") ||
    normalized.includes("qwen") ||
    normalized.includes("glm") ||
    normalized.includes("sonar") ||
    normalized.includes("mistral") ||
    normalized.includes("gpt-oss")
  ) {
    return { maxTokens: fallback, source: "provider-default" };
  }

  if (normalized.includes("llama")) {
    return {
      maxTokens: Math.max(8192, Math.min(fallback, 131072)),
      source: "provider-default",
    };
  }

  return { maxTokens: fallback, source: "provider-default" };
}

export function getContextWindowInfo(
  config: ApiConfig,
  backend?: LLMBackendId | null
): ContextWindowInfo {
  const providerId = resolveSelectedProviderId(config, backend);
  if (!providerId) {
    return {
      providerId: null,
      providerLabel: "Default",
      model: "",
      maxTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
      source: "fallback",
    };
  }

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
    LLM_BACKEND: "",
    DEEPSEEK_API_KEY: "",
    DEEPSEEK_MODEL: "",
    KIMI_API_KEY: "",
    KIMI_MODEL: "",
    OPENAI_COMPATIBLE_BASE_URL: "",
    OPENAI_COMPATIBLE_API_KEY: "",
    OPENAI_COMPATIBLE_MODEL: "",
    OLLAMA_URL: "",
    OLLAMA_MODEL: "",
    CLAW_CODE_ENABLED: "0",
    CLAW_CODE_MODEL: "",
    CLAW_CODE_BASE_URL: "",
    CLAW_CODE_API_KEY: "",
  };

  const providerId = config.preferred_backend;
  if (!providerId) return env;

  const provider = getProviderConfig(config, providerId);
  const runtimeBackend = resolveRuntimeBackend(providerId);
  env.LLM_BACKEND = runtimeBackend;

  switch (runtimeBackend) {
    case "deepseek":
      env.DEEPSEEK_API_KEY = provider.api_key;
      env.DEEPSEEK_MODEL = provider.model;
      env.CLAW_CODE_MODEL = provider.model;
      env.CLAW_CODE_BASE_URL = "https://api.deepseek.com/v1";
      env.CLAW_CODE_API_KEY = provider.api_key;
      break;
    case "kimi":
      env.KIMI_API_KEY = provider.api_key;
      env.KIMI_MODEL = provider.model;
      env.CLAW_CODE_MODEL = provider.model;
      env.CLAW_CODE_BASE_URL = "https://api.moonshot.cn/v1";
      env.CLAW_CODE_API_KEY = provider.api_key;
      break;
    case "openai-compatible":
      env.OPENAI_COMPATIBLE_BASE_URL = provider.base_url;
      env.OPENAI_COMPATIBLE_API_KEY = provider.api_key;
      env.OPENAI_COMPATIBLE_MODEL = provider.model;
      env.CLAW_CODE_MODEL = provider.model;
      env.CLAW_CODE_BASE_URL = provider.base_url;
      env.CLAW_CODE_API_KEY = provider.api_key;
      break;
    case "ollama":
      env.OLLAMA_URL = provider.base_url;
      env.OLLAMA_MODEL = provider.model;
      env.CLAW_CODE_MODEL = provider.model;
      env.CLAW_CODE_BASE_URL = `${provider.base_url.replace(/\/+$/, "")}/v1`;
      env.CLAW_CODE_API_KEY = "local-token";
      break;
    default:
      break;
  }

  return env;
}

/** 根据当前提供商从 config 中取出 API payload；backend 会映射为后端实际支持的运行时类型 */
export function getPayloadFromConfig(
  backend: string | null,
  config: ApiConfig
): Record<string, unknown> {
  const providerId =
    isProviderId(backend) ? backend : config.preferred_backend ?? null;
  if (!providerId) return {};

  const runtimeBackend = resolveRuntimeBackend(providerId);
  const provider = getProviderConfig(config, providerId);
  const payload: Record<string, unknown> = { backend: runtimeBackend };

  switch (runtimeBackend) {
    case "deepseek":
    case "kimi":
      if (provider.api_key) payload.api_key = provider.api_key;
      if (provider.model) payload.model = provider.model;
      break;
    case "openai-compatible":
      if (provider.base_url) payload.base_url = provider.base_url;
      if (provider.api_key) payload.api_key = provider.api_key;
      if (provider.model) payload.model = provider.model;
      break;
    case "ollama":
      if (provider.base_url) payload.ollama_url = provider.base_url;
      if (provider.model) payload.model = provider.model;
      break;
    default:
      break;
  }

  return payload;
}
