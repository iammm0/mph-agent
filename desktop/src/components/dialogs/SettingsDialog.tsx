import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { ContextMemorySidebar } from "../ContextMemorySidebar";
import { Icon } from "../Icon";
import { useTheme, ACCENT_PRESETS } from "../../context/ThemeContext";
import { useAppState } from "../../context/AppStateContext";
import {
  apiConfigToEnv,
  getProviderCatalog,
  getProviderConfig,
  getProviderLabel,
  getProviderMeta,
  loadApiConfig,
  resolveRuntimeBackend,
  saveApiConfig,
  type ApiConfig,
  type LLMBackendId,
  type ProviderCatalogEntry,
} from "../../lib/apiConfig";
import type { BridgeResponse, MyComsolModel } from "../../lib/types";
import {
  clearCaseLibraryRecords,
  loadCaseLibraryRecords,
  removeCaseLibraryRecord,
  type CaseLibraryRecord,
} from "../../lib/caseLibraryRecords";

type SettingsTab = "theme" | "llm" | "comsol" | "memory" | "models";

const TABS: { id: SettingsTab; label: string; icon: string }[] = [
  { id: "theme", label: "主题", icon: "colorfilter" },
  { id: "llm", label: "LLM 配置", icon: "cpu" },
  { id: "comsol", label: "COMSOL 配置", icon: "3dcube" },
  { id: "models", label: "模型管理", icon: "folder-2" },
  { id: "memory", label: "记忆管理", icon: "note-2" },
];

const PROVIDER_GROUP_LABELS: Record<ProviderCatalogEntry["group"], string> = {
  "china-direct": "国内直连",
  "overseas-relay": "海外中转兼容",
  "custom-gateway": "自定义 / 企业网关",
  local: "本地部署",
};

const PROVIDER_GROUP_ORDER: ProviderCatalogEntry["group"][] = [
  "china-direct",
  "overseas-relay",
  "custom-gateway",
  "local",
];

/** 卡片角标：短中文，避免英文 runtime 标签 */
function providerConnectionHint(providerId: LLMBackendId): string {
  const rt = resolveRuntimeBackend(providerId);
  if (rt === "ollama") return "本机";
  if (rt === "deepseek" || rt === "kimi") return "直连";
  return "兼容";
}

function buildComsolEnv(
  config: ApiConfig,
  workspaceDir: string | null
): Record<string, string> {
  return {
    MODEL_OUTPUT_DIR: workspaceDir ?? "",
    COMSOL_JAR_PATH: config.comsol_jar_path,
    JAVA_HOME: config.java_home,
  };
}

interface SettingsDialogProps {
  onClose?: () => void;
  pageMode?: boolean;
}

function formatTime(value: number | null): string {
  if (!value) return "未记录";
  return new Date(value).toLocaleString();
}

function parseMemoryItems(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) =>
      line
        .replace(/^[-*•]\s+/, "")
        .replace(/^\d+[.)、]\s+/, "")
        .trim()
    );
}

function serializeMemoryItems(items: string[]): string {
  return items
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => (/[:：]$/.test(item) ? item : `- ${item}`))
    .join("\n");
}

export function SettingsDialog({
  onClose,
  pageMode = false,
}: SettingsDialogProps) {
  const { themeMode, accentColor, setThemeMode, setAccentColor } = useTheme();
  const { state, dispatch } = useAppState();
  const cid = state.currentConversationId;

  const providerCatalog = useMemo(() => getProviderCatalog(), []);

  const [activeTab, setActiveTab] = useState<SettingsTab>("theme");
  const [apiConfig, setApiConfig] = useState<ApiConfig>(() => loadApiConfig());
  const [memoryItems, setMemoryItems] = useState<string[]>([]);
  const [memoryStatus, setMemoryStatus] = useState("");
  const [llmStatus, setLlmStatus] = useState("");
  const [comsolStatus, setComsolStatus] = useState("");
  const [ollamaTestResult, setOllamaTestResult] = useState<{
    ok: boolean;
    msg: string;
  } | null>(null);
  const [modelsList, setModelsList] = useState<MyComsolModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [caseRecords, setCaseRecords] = useState<CaseLibraryRecord[]>(() =>
    loadCaseLibraryRecords()
  );

  useEffect(() => {
    setApiConfig(loadApiConfig());
  }, []);

  const selectedProviderId =
    apiConfig.preferred_backend ?? providerCatalog[0]?.id ?? "deepseek";
  const selectedProviderMeta = getProviderMeta(selectedProviderId);
  const selectedProviderConfig = getProviderConfig(apiConfig, selectedProviderId);
  const selectedRuntimeHint = (() => {
    const rt = resolveRuntimeBackend(selectedProviderId);
    if (rt === "ollama") return "通过本地或局域网 Ollama 调用，无需 API Key。";
    if (rt === "deepseek") return "请求发往 DeepSeek 官方接口（Python 内置映射）。";
    if (rt === "kimi") return "请求发往 Moonshot 官方接口（Python 内置映射）。";
    return "按 OpenAI 兼容协议请求你填写的 Base URL，由 Python 映射为 openai-compatible 运行时。";
  })();
  const serializedMemoryText = useMemo(
    () => serializeMemoryItems(memoryItems),
    [memoryItems]
  );

  const providersByGroup = useMemo(() => {
    const groups: Record<
      ProviderCatalogEntry["group"],
      ProviderCatalogEntry[]
    > = {
      "china-direct": [],
      "overseas-relay": [],
      "custom-gateway": [],
      local: [],
    };
    for (const provider of providerCatalog) {
      groups[provider.group].push(provider);
    }
    return groups;
  }, [providerCatalog]);

  const openNativePath = useCallback((path: string) => {
    invoke("open_path", { path }).catch(() => {
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(path);
      }
    });
  }, []);

  const openInFolder = useCallback((path: string) => {
    invoke("open_in_folder", { path }).catch(() => {
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(path);
      }
    });
  }, []);

  const openPreviewMd = useCallback(
    (modelPath: string) => {
      const dir = modelPath.replace(/[/\\][^/\\]*$/, "") || modelPath;
      const mdPath =
        dir + (dir.endsWith("/") || dir.endsWith("\\") ? "" : "/") + "operations.md";
      openNativePath(mdPath);
    },
    [openNativePath]
  );

  const saveAndSync = useCallback(
    async (config: ApiConfig, section: "llm" | "comsol") => {
      saveApiConfig(config);
      const reloaded = loadApiConfig();
      setApiConfig(reloaded);

      const setStatus = section === "llm" ? setLlmStatus : setComsolStatus;
      setStatus("正在同步到后端...");

      try {
        const env =
          section === "llm"
            ? apiConfigToEnv(reloaded)
            : buildComsolEnv(reloaded, state.workspaceDir);
        const res = await invoke<{ ok: boolean; message: string }>("bridge_send", {
          cmd: "config_save",
          payload: { config: env },
        });
        if (res.ok && section === "llm" && reloaded.preferred_backend) {
          const p = getProviderConfig(reloaded, reloaded.preferred_backend);
          const label = getProviderLabel(reloaded.preferred_backend);
          setStatus(
            `已写入本页并同步后端。当前默认：${label}，模型「${p.model || "（未填）"}」。API Key 仍以密文框显示。`
          );
        } else {
          setStatus(res.ok ? `已保存：${res.message}` : res.message);
        }
      } catch (error) {
        setStatus(`同步失败：${String(error)}`);
      }

      window.setTimeout(() => setStatus(""), 6500);
    },
    [state.workspaceDir]
  );

  const setPreferredBackend = useCallback(
    (value: LLMBackendId) => {
      setApiConfig((current) => {
        const next = { ...current, preferred_backend: value };
        saveApiConfig(next);
        return next;
      });
      dispatch({ type: "SET_BACKEND", backend: value });
      setOllamaTestResult(null);
    },
    [dispatch]
  );

  const updateProviderField = useCallback(
    (
      providerId: LLMBackendId,
      field: keyof ReturnType<typeof getProviderConfig>,
      value: string
    ) => {
      setApiConfig((current) => ({
        ...current,
        providers: {
          ...current.providers,
          [providerId]: {
            ...getProviderConfig(current, providerId),
            [field]: value,
          },
        },
      }));
      if (providerId === "ollama") {
        setOllamaTestResult(null);
      }
    },
    []
  );

  const saveConfig = useCallback(() => {
    const nextConfig = apiConfig.preferred_backend
      ? apiConfig
      : { ...apiConfig, preferred_backend: selectedProviderId };

    if (!apiConfig.preferred_backend) {
      saveApiConfig(nextConfig);
      setApiConfig(nextConfig);
      dispatch({ type: "SET_BACKEND", backend: selectedProviderId });
    }

    void saveAndSync(nextConfig, "llm");
  }, [apiConfig, dispatch, saveAndSync, selectedProviderId]);

  const pickWorkspaceDir = useCallback(async () => {
    const selected = await open({
      directory: true,
      multiple: false,
      title: "选择建模工作目录（mph 输出目录）",
      defaultPath: state.workspaceDir || undefined,
    });
    if (selected == null) return;
    dispatch({ type: "SET_WORKSPACE_DIR", path: String(selected) });
    setComsolStatus("工作目录已更新，请点击保存同步到后端");
  }, [state.workspaceDir, dispatch]);

  const clearWorkspaceDir = useCallback(() => {
    dispatch({ type: "SET_WORKSPACE_DIR", path: null });
    setComsolStatus("工作目录已清除，请点击保存同步到后端");
  }, [dispatch]);

  const pickDirectory = useCallback(
    (title: string, currentPath: string, onPick: (path: string) => void) => {
      open({
        directory: true,
        multiple: false,
        title,
        defaultPath: currentPath || undefined,
      }).then((selected) => {
        if (selected != null) onPick(String(selected));
      });
    },
    []
  );

  const testOllama = useCallback(async () => {
    const url = getProviderConfig(apiConfig, "ollama").base_url.trim();
    setOllamaTestResult(null);
    try {
      const res = await invoke<{ ok: boolean; message: string }>("bridge_send", {
        cmd: "ollama_ping",
        payload: { ollama_url: url },
      });
      setOllamaTestResult({ ok: res.ok, msg: res.message });
    } catch (error) {
      setOllamaTestResult({ ok: false, msg: String(error) });
    }
  }, [apiConfig]);

  const loadMemory = useCallback(async () => {
    if (!cid) {
      setMemoryStatus("当前没有会话");
      return;
    }
    setMemoryStatus("加载中...");
    try {
      const res = await invoke<{ ok: boolean; message: string }>("bridge_send", {
        cmd: "context_get_summary",
        payload: { conversation_id: cid },
      });
      setMemoryItems(res.ok ? parseMemoryItems(res.message) : []);
      setMemoryStatus(res.ok ? "已加载" : res.message);
    } catch (error) {
      setMemoryStatus(`加载失败：${String(error)}`);
    }
    window.setTimeout(() => setMemoryStatus(""), 3000);
  }, [cid]);

  const saveMemory = useCallback(async () => {
    if (!cid) {
      setMemoryStatus("当前没有会话");
      return;
    }
    setMemoryStatus("保存中...");
    try {
      const res = await invoke<{ ok: boolean; message: string }>("bridge_send", {
        cmd: "context_set_summary",
        payload: { conversation_id: cid, text: serializedMemoryText },
      });
      setMemoryStatus(res.ok ? "记忆已保存" : res.message);
    } catch (error) {
      setMemoryStatus(`保存失败：${String(error)}`);
    }
    window.setTimeout(() => setMemoryStatus(""), 3000);
  }, [cid, serializedMemoryText]);

  const clearMemory = useCallback(async () => {
    if (!cid) return;
    if (!confirm("确定清除本会话的对话历史与记忆吗？")) return;
    setMemoryStatus("清除中...");
    try {
      const res = await invoke<{ ok: boolean; message: string }>("bridge_send", {
        cmd: "context_clear",
        payload: { conversation_id: cid },
      });
      setMemoryItems([]);
      setMemoryStatus(res.ok ? "已清除" : res.message);
    } catch (error) {
      setMemoryStatus(`清除失败：${String(error)}`);
    }
    window.setTimeout(() => setMemoryStatus(""), 3000);
  }, [cid]);

  const addMemoryItem = useCallback(() => {
    setMemoryItems((current) => [...current, ""]);
  }, []);

  const updateMemoryItem = useCallback((index: number, value: string) => {
    setMemoryItems((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? value : item))
    );
  }, []);

  const removeMemoryItem = useCallback((index: number) => {
    setMemoryItems((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }, []);

  const loadModelsList = useCallback(async () => {
    setModelsLoading(true);
    try {
      const res = await invoke<BridgeResponse>("bridge_send", {
        cmd: "models_list",
        payload: { limit: 80 },
      });
      setModelsList(res.ok && Array.isArray(res.models) ? res.models : []);
    } catch {
      setModelsList([]);
    } finally {
      setModelsLoading(false);
    }
  }, []);

  const reloadCaseRecords = useCallback(() => {
    setCaseRecords(loadCaseLibraryRecords());
  }, []);

  useEffect(() => {
    if (activeTab !== "models") return;
    void loadModelsList();
    reloadCaseRecords();
  }, [activeTab, loadModelsList, reloadCaseRecords]);

  const handleRemoveCaseRecord = useCallback((id: string) => {
    setCaseRecords(removeCaseLibraryRecord(id));
  }, []);

  const handleClearCaseRecords = useCallback(() => {
    clearCaseLibraryRecords();
    setCaseRecords([]);
  }, []);

  const renderRow = (label: string, control: ReactNode, rowKey?: string) => (
    <div
      className={`settings-pane-row ${!label ? "settings-pane-row--full" : ""}`}
      key={rowKey ?? (label || "action")}
    >
      <span className="settings-pane-label">{label}</span>
      <span className="settings-pane-control">{control}</span>
    </div>
  );

  return (
    <div className={`settings-dialog ${pageMode ? "settings-dialog--page" : ""}`}>
      <header className="settings-dialog-header">
        <div>
          <h2 className="settings-dialog-title">设置中心</h2>
          {pageMode && (
            <p className="settings-hint">
              集中管理案例库记录、技能系统、LLM 提供商、COMSOL 环境、主题与模型资产。
            </p>
          )}
        </div>
        {!pageMode && onClose && (
          <button
            type="button"
            className="settings-dialog-close"
            onClick={onClose}
            aria-label="关闭"
          >
            <Icon name="close-circle" size={16} />
          </button>
        )}
      </header>
      <div className="settings-dialog-body">
        <nav className="settings-sidebar" aria-label="设置分类">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`settings-sidebar-item ${
                activeTab === tab.id ? "active" : ""
              }`}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon name={tab.icon} size={16} className="settings-sidebar-icon" />
              <span className="settings-sidebar-label">{tab.label}</span>
            </button>
          ))}
        </nav>

        <div className="settings-pane">
          {activeTab === "theme" && (
            <div className="settings-card">
              {renderRow(
                "外观",
                <div className="theme-toggle">
                  <button
                    type="button"
                    className={`theme-toggle-btn ${
                      themeMode === "light" ? "active" : ""
                    }`}
                    onClick={() => setThemeMode("light")}
                  >
                    <Icon name="sun" size={14} />
                    浅色
                  </button>
                  <button
                    type="button"
                    className={`theme-toggle-btn ${
                      themeMode === "dark" ? "active" : ""
                    }`}
                    onClick={() => setThemeMode("dark")}
                  >
                    <Icon name="moon" size={14} />
                    深色
                  </button>
                  <button
                    type="button"
                    className={`theme-toggle-btn ${
                      themeMode === "system" ? "active" : ""
                    }`}
                    onClick={() => setThemeMode("system")}
                  >
                    <Icon name="monitor" size={14} />
                    跟随系统
                  </button>
                </div>
              )}
              {renderRow(
                "强调色",
                <>
                  <div className="accent-chips">
                    {ACCENT_PRESETS.map((preset) => (
                      <button
                        key={preset.value}
                        type="button"
                        className={`accent-chip ${
                          accentColor === preset.value ? "active" : ""
                        }`}
                        style={{ backgroundColor: preset.value }}
                        onClick={() => setAccentColor(preset.value)}
                        title={preset.name}
                      >
                        {preset.name}
                      </button>
                    ))}
                  </div>
                  <input
                    type="color"
                    className="accent-color-input"
                    value={accentColor}
                    onChange={(event) => setAccentColor(event.target.value)}
                  />
                  <span className="accent-hex">{accentColor}</span>
                </>
              )}
            </div>
          )}

          {activeTab === "llm" && (
            <div className="settings-card">
              <p className="settings-hint">
                下方按使用场景分组；保存后表单会重新载入本地配置。后端实际仍映射为四类协议：DeepSeek、Kimi、Ollama、OpenAI
                兼容。
              </p>

              <div className="settings-provider-groups">
                {PROVIDER_GROUP_ORDER.map((group) => {
                  const providers = providersByGroup[group];
                  if (providers.length === 0) return null;
                  return (
                    <section key={group} className="settings-provider-section">
                      <div className="settings-provider-section-title">
                        {PROVIDER_GROUP_LABELS[group]}
                      </div>
                      <div className="settings-provider-grid">
                        {providers.map((provider) => {
                          const active = apiConfig.preferred_backend === provider.id;
                          return (
                            <button
                              key={provider.id}
                              type="button"
                              className={`settings-provider-card ${
                                active ? "active" : ""
                              }`}
                              onClick={() => setPreferredBackend(provider.id)}
                              title={provider.description}
                            >
                              <span className="settings-provider-card-head">
                                <span className="settings-provider-card-name">
                                  {provider.label}
                                </span>
                                <span className="settings-provider-card-runtime">
                                  {providerConnectionHint(provider.id)}
                                </span>
                              </span>
                              <span className="settings-provider-card-desc">
                                {provider.description}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </div>

              <div className="settings-provider-detail">
                <div className="settings-provider-detail-head">
                  <div>
                    <h3 className="settings-pane-title">{selectedProviderMeta.label}</h3>
                    <p className="settings-hint">{selectedProviderMeta.description}</p>
                  </div>
                  <p className="settings-provider-detail-runtime">{selectedRuntimeHint}</p>
                </div>

                {renderRow(
                  "默认提供商",
                  <span className="settings-provider-selected">
                    {apiConfig.preferred_backend
                      ? `${selectedProviderMeta.label}（已启用）`
                      : `${selectedProviderMeta.label}（编辑中，保存时将设为默认）`}
                  </span>,
                  "provider-selected"
                )}

                {selectedProviderMeta.supportsBaseUrl &&
                  renderRow(
                    selectedProviderMeta.baseUrlLabel ?? "接口地址",
                    <input
                      type="url"
                      className="dialog-input settings-api-input"
                      placeholder={
                        selectedProviderMeta.defaultBaseUrl || "https://api.example.com/v1"
                      }
                      value={selectedProviderConfig.base_url}
                      onChange={(event) =>
                        updateProviderField(
                          selectedProviderId,
                          "base_url",
                          event.target.value
                        )
                      }
                    />
                  )}

                {selectedProviderMeta.requiresApiKey &&
                  renderRow(
                    "API 密钥",
                    <div className="settings-pane-stack">
                      <input
                        type="password"
                        className="dialog-input settings-api-input"
                        placeholder={`填写 ${selectedProviderMeta.label} 的密钥`}
                        value={selectedProviderConfig.api_key}
                        onChange={(event) =>
                          updateProviderField(
                            selectedProviderId,
                            "api_key",
                            event.target.value
                          )
                        }
                      />
                      <p className="settings-field-note">
                        保存后仍显示为圆点属正常；是否生效以保存后下方提示里的模型名为准。
                      </p>
                    </div>
                  )}

                {renderRow(
                  "模型",
                  <input
                    type="text"
                    className="dialog-input settings-api-input"
                    placeholder={selectedProviderMeta.defaultModel}
                    value={selectedProviderConfig.model}
                    onChange={(event) =>
                      updateProviderField(
                        selectedProviderId,
                        "model",
                        event.target.value
                      )
                    }
                  />
                )}

                {selectedProviderId === "ollama" &&
                  renderRow(
                    "",
                    <>
                      <button
                        type="button"
                        className="dialog-btn secondary"
                        onClick={testOllama}
                      >
                        测试连接
                      </button>
                      {ollamaTestResult && (
                        <span
                          className={`settings-status ${
                            ollamaTestResult.ok
                              ? "settings-status-ok"
                              : "settings-status-err"
                          }`}
                        >
                          {ollamaTestResult.msg}
                        </span>
                      )}
                    </>,
                    "ollama-test"
                  )}

                {renderRow(
                  "",
                  <>
                    <button type="button" className="dialog-btn primary" onClick={saveConfig}>
                      保存 LLM 配置
                    </button>
                    {llmStatus && <span className="settings-status">{llmStatus}</span>}
                  </>,
                  "llm-save"
                )}
              </div>
            </div>
          )}

          {activeTab === "comsol" && (
            <div className="settings-card">
              <p className="settings-hint">
                管理面向 COMSOL Multiphysics 6.3 自动建模所需的输出目录、JAR 路径和 Java 运行环境。
                当前官方支持 Windows x64 与 macOS Apple Silicon：Windows 选择
                <code>C:\Program Files\COMSOL\COMSOL63\Multiphysics\plugins</code>，
                Apple Silicon 选择 <code>/Applications/COMSOL63/Multiphysics/plugins</code>。
              </p>

              <div className="settings-field">
                <label>建模工作目录（MODEL_OUTPUT_DIR）</label>
                <div className="settings-path-row">
                  <input
                    type="text"
                    className="dialog-input settings-api-input settings-path-input"
                    placeholder="未设置时使用默认输出目录"
                    value={state.workspaceDir ?? ""}
                    readOnly
                  />
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={pickWorkspaceDir}
                  >
                    选择目录
                  </button>
                  {state.workspaceDir && (
                    <button
                      type="button"
                      className="dialog-btn secondary"
                      onClick={clearWorkspaceDir}
                    >
                      清除
                    </button>
                  )}
                </div>
              </div>

              <div className="settings-field">
                <label>COMSOL 6.3 plugins 目录（COMSOL_JAR_PATH）</label>
                <div className="settings-path-row">
                  <input
                    type="text"
                    className="dialog-input settings-api-input settings-path-input"
                    placeholder="Windows: ...\COMSOL63\Multiphysics\plugins；macOS: /Applications/COMSOL63/Multiphysics/plugins"
                    value={apiConfig.comsol_jar_path}
                    readOnly
                  />
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={() =>
                      pickDirectory(
                        "选择 COMSOL 6.3 plugins 目录",
                        apiConfig.comsol_jar_path,
                        (path) =>
                          setApiConfig((config) => ({
                            ...config,
                            comsol_jar_path: path,
                          }))
                      )
                    }
                  >
                    选择目录
                  </button>
                  {apiConfig.comsol_jar_path && (
                    <button
                      type="button"
                      className="dialog-btn secondary"
                      onClick={() =>
                        setApiConfig((config) => ({
                          ...config,
                          comsol_jar_path: "",
                        }))
                      }
                    >
                      清除
                    </button>
                  )}
                </div>
              </div>

              <div className="settings-field">
                <label>Java 8 / 11 环境（JAVA_HOME）</label>
                <div className="settings-path-row">
                  <input
                    type="text"
                    className="dialog-input settings-api-input settings-path-input"
                    placeholder="未选择时使用内置或系统 Java"
                    value={apiConfig.java_home}
                    readOnly
                  />
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={() =>
                      pickDirectory(
                        "选择 Java 8 或 11 安装目录",
                        apiConfig.java_home,
                        (path) =>
                          setApiConfig((config) => ({ ...config, java_home: path }))
                      )
                    }
                  >
                    选择目录
                  </button>
                  {apiConfig.java_home && (
                    <button
                      type="button"
                      className="dialog-btn secondary"
                      onClick={() =>
                        setApiConfig((config) => ({ ...config, java_home: "" }))
                      }
                    >
                      清除
                    </button>
                  )}
                </div>
              </div>

              {renderRow(
                "",
                <>
                  <button
                    type="button"
                    className="dialog-btn primary"
                    onClick={() => void saveAndSync(apiConfig, "comsol")}
                  >
                    保存 COMSOL 配置
                  </button>
                  {comsolStatus && <span className="settings-status">{comsolStatus}</span>}
                </>,
                "comsol-save"
              )}
            </div>
          )}

          {activeTab === "memory" && (
            <>
              <div className="settings-card">
                <h3 className="settings-pane-title">记忆预览（Bridge）</h3>
                <p className="settings-hint">
                  展示当前会话在 Bridge 侧已整理的摘要，以及下一轮将注入提示词的上下文。需已选择会话且 Bridge 就绪；打开本页或切换到此标签时会自动尝试刷新。
                </p>
                <ContextMemorySidebar embedded />
              </div>

              <div className="settings-card">
              <p className="settings-hint">
                当前会话的摘要记忆会参与后续推理。这里改为分条整理，每条记忆单独维护，保存时会自动整理成项目符号列表。
              </p>

              {renderRow(
                "",
                <div className="settings-memory-actions">
                  <button type="button" className="dialog-btn secondary" onClick={loadMemory}>
                    加载
                  </button>
                  <button type="button" className="dialog-btn primary" onClick={saveMemory}>
                    保存
                  </button>
                  <button type="button" className="dialog-btn secondary" onClick={addMemoryItem}>
                    新增条目
                  </button>
                  <button type="button" className="dialog-btn secondary" onClick={clearMemory}>
                    清除本会话记忆
                  </button>
                </div>,
                "memory-actions"
              )}

              <div className="settings-field">
                <label>会话记忆条目</label>
                <div className="settings-memory-list">
                  {memoryItems.length === 0 && (
                    <div className="settings-memory-empty">
                      暂无记忆条目，可先点击“加载”或“新增条目”。
                    </div>
                  )}
                  {memoryItems.map((item, index) => (
                    <div key={`memory-item-${index}`} className="settings-memory-item">
                      <span className="settings-memory-item-index">{index + 1}</span>
                      <textarea
                        className="dialog-input settings-memory-item-input"
                        placeholder="输入一条记忆，例如：常用单位是 mm。"
                        value={item}
                        onChange={(event) => updateMemoryItem(index, event.target.value)}
                        rows={2}
                      />
                      <button
                        type="button"
                        className="dialog-btn secondary"
                        onClick={() => removeMemoryItem(index)}
                      >
                        删除
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="settings-field">
                <label>保存预览</label>
                <pre className="settings-memory-preview">
                  {serializedMemoryText || "暂无可保存的记忆内容。"}
                </pre>
              </div>

              {memoryStatus && <div className="settings-status">{memoryStatus}</div>}
            </div>
            </>
          )}

          {activeTab === "models" && (
            <div className="settings-pane-rows">
              <div className="settings-card">
                <div className="settings-card-head">
                  <div>
                    <h3 className="settings-pane-title">案例库模型记录</h3>
                    <p className="settings-hint">
                      这里管理从案例库点击“查看详情”或“下载案例”时留下的记录，方便再次打开或清理。
                    </p>
                  </div>
                  <div className="settings-models-item-actions">
                    <button
                      type="button"
                      className="dialog-btn secondary"
                      onClick={reloadCaseRecords}
                    >
                      刷新记录
                    </button>
                    {caseRecords.length > 0 && (
                      <button
                        type="button"
                        className="dialog-btn secondary"
                        onClick={handleClearCaseRecords}
                      >
                        清空记录
                      </button>
                    )}
                  </div>
                </div>

                <div className="settings-models-list">
                  {caseRecords.length === 0 && (
                    <div className="settings-models-empty">暂无案例库模型记录</div>
                  )}
                  {caseRecords.map((record) => (
                    <div
                      key={record.id}
                      className="settings-models-item settings-models-item--stacked"
                    >
                      <div className="settings-models-item-main">
                        <span
                          className="settings-models-item-title"
                          title={record.officialUrl}
                        >
                          {record.title}
                        </span>
                        <span className="settings-models-item-subtitle">
                          {record.category || "未分类"} · 查看 {record.viewCount} 次 · 下载{" "}
                          {record.downloadCount} 次 · 最近下载：{formatTime(record.lastDownloadedAt)}
                        </span>
                      </div>
                      <div className="settings-models-item-actions">
                        <button
                          type="button"
                          className="dialog-btn secondary"
                          onClick={() => openNativePath(record.officialUrl)}
                        >
                          查看详情
                        </button>
                        <button
                          type="button"
                          className="dialog-btn secondary"
                          onClick={() => openNativePath(record.downloadUrl)}
                        >
                          再次下载
                        </button>
                        <button
                          type="button"
                          className="dialog-btn secondary"
                          onClick={() => handleRemoveCaseRecord(record.id)}
                        >
                          移除记录
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="settings-card">
                <div className="settings-card-head">
                  <div>
                    <h3 className="settings-pane-title">我创建的 COMSOL 模型</h3>
                    <p className="settings-hint">
                      以下为各会话中生成过的 COMSOL 模型，可打开目录或预览 operations.md。
                    </p>
                  </div>
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={loadModelsList}
                    disabled={modelsLoading}
                  >
                    {modelsLoading ? "加载中..." : "刷新列表"}
                  </button>
                </div>

                <div className="settings-models-list">
                  {modelsLoading && modelsList.length === 0 && (
                    <div className="settings-models-loading">加载中...</div>
                  )}
                  {!modelsLoading && modelsList.length === 0 && (
                    <div className="settings-models-empty">暂无模型记录</div>
                  )}
                  {modelsList.map((model) => (
                    <div key={model.path} className="settings-models-item">
                      <span className="settings-models-item-title" title={model.path}>
                        {model.title}
                        {model.is_latest && (
                          <span className="settings-models-item-latest">最新</span>
                        )}
                      </span>
                      <div className="settings-models-item-actions">
                        <button
                          type="button"
                          className="dialog-btn secondary"
                          onClick={() => openInFolder(model.path)}
                        >
                          打开目录
                        </button>
                        <button
                          type="button"
                          className="dialog-btn secondary"
                          onClick={() => openPreviewMd(model.path)}
                        >
                          预览
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
