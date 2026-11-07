import { useCallback, useEffect, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Icon } from "../Icon";
import { useTheme, ACCENT_PRESETS } from "../../context/ThemeContext";
import { useAppState } from "../../context/AppStateContext";
import {
  apiConfigToEnv,
  COMPUTE_PREFERENCE_OPTIONS,
  getProviderConfig,
  getProviderMeta,
  loadApiConfig,
  saveApiConfig,
  type ApiConfig,
  type ComputePreference,
  type LLMBackendId,
} from "../../lib/apiConfig";
import type { BridgeResponse, MyComsolModel, SettingsSection } from "../../lib/types";
import { CaseLibraryPage } from "../CaseLibraryPage";
import { ModelPicker } from "../ModelPicker";
import {
  clearCaseLibraryRecords,
  loadCaseLibraryRecords,
  removeCaseLibraryRecord,
  type CaseLibraryRecord,
} from "../../lib/caseLibraryRecords";

const TABS: { id: SettingsSection; label: string; icon: string; group: "config" | "library" }[] = [
  { id: "theme", label: "主题", icon: "colorfilter", group: "config" },
  { id: "llm", label: "模型配置", icon: "cpu", group: "config" },
  { id: "comsol", label: "COMSOL", icon: "3dcube", group: "config" },
  { id: "models", label: "仿真产物", icon: "folder-2", group: "config" },
  { id: "case-library", label: "案例库", icon: "book", group: "library" },
];

const ACTIVE_PROVIDER_ID: LLMBackendId = "deepseek";

function modelsDirOf(workspaceDir: string | null): string {
  if (!workspaceDir) return "";
  const sep = workspaceDir.includes("\\") ? "\\" : "/";
  const trimmed = workspaceDir.replace(/[/\\]+$/, "");
  return `${trimmed}${sep}models`;
}

function buildComsolEnv(
  config: ApiConfig,
  workspaceDir: string | null
): Record<string, string> {
  return {
    MODEL_OUTPUT_DIR: modelsDirOf(workspaceDir),
    COMSOL_JAR_PATH: config.comsol_jar_path,
    JAVA_HOME: config.java_home,
    COMSOL_COMPUTE_PREFERENCE: config.compute_preference || "auto",
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

export function SettingsDialog({
  onClose,
  pageMode = false,
}: SettingsDialogProps) {
  const { themeMode, accentColor, setThemeMode, setAccentColor } = useTheme();
  const { state, dispatch } = useAppState();

  const activeTab = state.settingsTab;
  const setActiveTab = (tab: SettingsSection) =>
    dispatch({ type: "SET_VIEW", view: "settings", settingsTab: tab });
  const [apiConfig, setApiConfig] = useState<ApiConfig>(() => loadApiConfig());
  const [llmStatus, setLlmStatus] = useState("");
  const [llmStatusKind, setLlmStatusKind] = useState<"ok" | "err" | "">("");
  const [comsolStatus, setComsolStatus] = useState("");
  const [modelsList, setModelsList] = useState<MyComsolModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [caseRecords, setCaseRecords] = useState<CaseLibraryRecord[]>(() =>
    loadCaseLibraryRecords()
  );

  useEffect(() => {
    const loaded = loadApiConfig();
    setApiConfig(loaded);
    if (state.backend !== ACTIVE_PROVIDER_ID) {
      dispatch({ type: "SET_BACKEND", backend: ACTIVE_PROVIDER_ID });
    }
  }, [dispatch, state.backend]);

  const selectedProviderId = ACTIVE_PROVIDER_ID;
  const selectedProviderMeta = getProviderMeta(ACTIVE_PROVIDER_ID);
  const selectedProviderConfig = getProviderConfig(apiConfig, selectedProviderId);

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
    async (
      config: ApiConfig,
      section: "llm" | "comsol",
      options?: { probeKey?: boolean }
    ) => {
      saveApiConfig(config);
      const reloaded = loadApiConfig();
      setApiConfig(reloaded);

      const setStatus = section === "llm" ? setLlmStatus : setComsolStatus;
      if (section === "llm") setLlmStatusKind("");
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
        if (!res.ok) {
          if (section === "llm") setLlmStatusKind("err");
          setStatus(res.message);
          window.setTimeout(() => {
            setStatus("");
            if (section === "llm") setLlmStatusKind("");
          }, 8000);
          return;
        }

        if (section !== "llm" || !options?.probeKey) {
          setStatus(section === "llm" ? "已保存" : `已保存：${res.message}`);
          window.setTimeout(() => setStatus(""), 6500);
          return;
        }

        const apiKey = getProviderConfig(reloaded, ACTIVE_PROVIDER_ID).api_key.trim();
        if (!apiKey) {
          setLlmStatusKind("err");
          setStatus("已保存，但未填写 API 密钥，无法探测");
          window.setTimeout(() => {
            setStatus("");
            setLlmStatusKind("");
          }, 8000);
          return;
        }

        setStatus("已保存，正在探测密钥…");
        const probe = await invoke<{
          ok: boolean;
          message: string;
          models?: string[];
        }>("bridge_send", {
          cmd: "deepseek_models",
          payload: { api_key: apiKey },
        });
        const models = (probe.models ?? []).filter((item) => item.trim());
        if (probe.ok && models.length > 0) {
          setLlmStatusKind("ok");
          setStatus(`密钥可用 · ${probe.message}：${models.join("、")}`);
        } else {
          setLlmStatusKind("err");
          const message = probe.message || "未探测到模型";
          setStatus(
            message.includes("未知命令")
              ? "已保存，但探测命令尚未加载，请重启桌面端后再试"
              : `密钥不可用 · ${message}`
          );
        }
      } catch (error) {
        if (section === "llm") setLlmStatusKind("err");
        setStatus(`同步失败：${String(error)}`);
      }

      window.setTimeout(() => {
        setStatus("");
        if (section === "llm") setLlmStatusKind("");
      }, 10000);
    },
    [state.workspaceDir]
  );

  const updateProviderField = useCallback(
    (
      providerId: LLMBackendId,
      field: keyof ReturnType<typeof getProviderConfig>,
      value: string
    ) => {
      setApiConfig((current) => ({
        ...current,
        preferred_backend: ACTIVE_PROVIDER_ID,
        providers: {
          ...current.providers,
          [providerId]: {
            ...getProviderConfig(current, providerId),
            [field]: value,
          },
        },
      }));
    },
    []
  );

  const saveConfig = useCallback(() => {
    const nextConfig = {
      ...apiConfig,
      preferred_backend: ACTIVE_PROVIDER_ID,
    };
    saveApiConfig(nextConfig);
    setApiConfig(nextConfig);
    dispatch({ type: "SET_BACKEND", backend: ACTIVE_PROVIDER_ID });
    void saveAndSync(nextConfig, "llm", { probeKey: true });
  }, [apiConfig, dispatch, saveAndSync]);

  const pickWorkspaceDir = useCallback(async () => {
    const cid = state.currentConversationId;
    if (!cid) {
      setComsolStatus("请先在侧边栏新建工作空间");
      return;
    }
    const selected = await open({
      directory: true,
      multiple: false,
      title: "修改当前工作空间目录",
      defaultPath: state.workspaceDir || undefined,
    });
    if (selected == null) return;
    dispatch({
      type: "SET_CONVERSATION_WORKSPACE_DIR",
      id: cid,
      path: String(selected),
    });
    setComsolStatus("当前工作空间目录已更新，请点击保存同步到后端");
  }, [state.currentConversationId, state.workspaceDir, dispatch]);

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
        {pageMode ? (
          <button
            type="button"
            className="settings-back"
            onClick={() => dispatch({ type: "SET_VIEW", view: "session" })}
          >
            <Icon name="arrow-left-01" size={15} />
            返回应用
          </button>
        ) : (
          <>
            <h2 className="settings-dialog-title">设置</h2>
            {onClose && (
              <button
                type="button"
                className="settings-dialog-close"
                onClick={onClose}
                aria-label="关闭"
              >
                <Icon name="close-circle" size={16} />
              </button>
            )}
          </>
        )}
      </header>
      <div className="settings-dialog-body">
        <nav className="settings-sidebar" aria-label="设置分类">
          {TABS.map((tab, index) => (
            <span key={tab.id} className="settings-sidebar-slot">
              {index > 0 && TABS[index - 1].group !== tab.group ? (
                <span className="settings-sidebar-divider" />
              ) : null}
              <button
                type="button"
                className={`settings-sidebar-item ${
                  activeTab === tab.id ? "active" : ""
                }`}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon name={tab.icon} size={16} className="settings-sidebar-icon" />
                <span className="settings-sidebar-label">{tab.label}</span>
              </button>
            </span>
          ))}
        </nav>

        <div
          className={`settings-pane${
            activeTab === "case-library" ? " settings-pane--fill" : ""
          }`}
        >
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
            <div className="settings-card settings-model-form">
              <div className="settings-field">
                <label>模型</label>
                <ModelPicker
                  variant="field"
                  apiKey={selectedProviderConfig.api_key}
                  model={selectedProviderConfig.model || selectedProviderMeta.defaultModel}
                  onSelect={(model) => {
                    const next = {
                      ...apiConfig,
                      preferred_backend: ACTIVE_PROVIDER_ID,
                      providers: {
                        ...apiConfig.providers,
                        [selectedProviderId]: {
                          ...selectedProviderConfig,
                          model,
                        },
                      },
                    };
                    setApiConfig(next);
                    void saveAndSync(next, "llm");
                  }}
                />
                <p className="settings-field-note">
                  打开列表会向 DeepSeek 探测可用模型。对话输入框里也可以直接切换。
                </p>
              </div>

              <div className="settings-field">
                <label htmlFor="settings-api-key">API 密钥</label>
                <input
                  id="settings-api-key"
                  type="password"
                  className="dialog-input settings-api-input"
                  placeholder="粘贴 DeepSeek API Key"
                  value={selectedProviderConfig.api_key}
                  onChange={(event) =>
                    updateProviderField(
                      selectedProviderId,
                      "api_key",
                      event.target.value
                    )
                  }
                />
              </div>

              <div className="settings-model-actions">
                <button type="button" className="dialog-btn primary" onClick={saveConfig}>
                  保存并探测
                </button>
                {llmStatus && (
                  <span
                    className={`settings-status${
                      llmStatusKind === "ok"
                        ? " settings-status-ok"
                        : llmStatusKind === "err"
                          ? " settings-status-err"
                          : ""
                    }`}
                  >
                    {llmStatus}
                  </span>
                )}
              </div>
            </div>
          )}

          {activeTab === "comsol" && (
            <div className="settings-card">
              <div className="settings-field">
                <label>工作空间</label>
                <div className="settings-path-row">
                  <input
                    type="text"
                    className="dialog-input settings-api-input settings-path-input"
                    placeholder={
                      state.currentConversationId
                        ? "尚未绑定目录"
                        : "请先新建工作空间"
                    }
                    value={state.workspaceDir ?? ""}
                    readOnly
                  />
                  <button
                    type="button"
                    className="dialog-btn secondary"
                    onClick={pickWorkspaceDir}
                    disabled={!state.currentConversationId}
                  >
                    修改
                  </button>
                </div>
              </div>

              <div className="settings-field">
                <label>COMSOL plugins</label>
                <div className="settings-path-row">
                  <input
                    type="text"
                    className="dialog-input settings-api-input settings-path-input"
                    placeholder="COMSOL63/Multiphysics/plugins"
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
                    选择
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
                <label>JAVA_HOME</label>
                <div className="settings-path-row">
                  <input
                    type="text"
                    className="dialog-input settings-api-input settings-path-input"
                    placeholder="留空则使用内置或系统 Java"
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
                    选择
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

              <div className="settings-field">
                <label>求解计算偏好</label>
                <p className="settings-hint">
                  跑任务前可切换。COMSOL 6.3 的 GPU 仅覆盖部分场景（如时间显式声学）；结构/传热多数仍走
                  CPU。
                </p>
                <div className="settings-compute-prefs" role="radiogroup" aria-label="计算偏好">
                  {COMPUTE_PREFERENCE_OPTIONS.map((opt) => {
                    const selected =
                      (apiConfig.compute_preference || "auto") === opt.id;
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        className={`settings-compute-pref${selected ? " is-selected" : ""}`}
                        onClick={() =>
                          setApiConfig((config) => ({
                            ...config,
                            compute_preference: opt.id as ComputePreference,
                          }))
                        }
                      >
                        <strong>{opt.label}</strong>
                        <span>{opt.hint}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="settings-model-actions">
                <button
                  type="button"
                  className="dialog-btn primary"
                  onClick={() => void saveAndSync(apiConfig, "comsol")}
                >
                  保存
                </button>
                {comsolStatus && <span className="settings-status">{comsolStatus}</span>}
              </div>
            </div>
          )}

          {activeTab === "models" && (
            <div className="settings-pane-rows">
              <div className="settings-card">
                <div className="settings-card-head">
                  <h3 className="settings-pane-title">案例记录</h3>
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
                          onClick={() =>
                            openNativePath(
                              record.localDir ||
                                record.localPaths?.[0] ||
                                record.downloadUrl
                            )
                          }
                        >
                          {record.localDir || record.localPaths?.[0]
                            ? "打开本地"
                            : "打开下载链接"}
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
                  <h3 className="settings-pane-title">我创建的模型</h3>
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
          {activeTab === "case-library" && <CaseLibraryPage />}
        </div>
      </div>
    </div>
  );
}
