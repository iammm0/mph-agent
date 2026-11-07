import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useAppState } from "../context/AppStateContext";
import { ConfirmDialog } from "./dialogs/ConfirmDialog";
import { CreateWorkspaceDialog } from "./dialogs/CreateWorkspaceDialog";
import { Icon } from "./Icon";
import type { Conversation } from "../lib/types";

const SIDEBAR_COLLAPSED_KEY = "mph-agent-sidebar-collapsed";
const SIDEBAR_WIDTH_KEY = "mph-agent-sidebar-width";
const SIDEBAR_DEFAULT_WIDTH = 260;
const SIDEBAR_MIN_WIDTH = 180;
const SIDEBAR_MAX_WIDTH = 520;
const SIDEBAR_COLLAPSED_WIDTH = 56;

function clampSidebarWidth(width: number): number {
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(width)));
}

function loadSidebarWidth(): number {
  try {
    const raw = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    const n = raw ? Number(raw) : NaN;
    if (Number.isFinite(n)) return clampSidebarWidth(n);
  } catch {
    // ignore
  }
  return SIDEBAR_DEFAULT_WIDTH;
}

function folderName(path: string | null | undefined): string {
  if (!path) return "工作空间";
  return path.split(/[/\\]/).filter(Boolean).pop() || "工作空间";
}

function normPath(path: string | null | undefined): string {
  return (path || "").trim().replace(/[/\\]+$/, "");
}

interface WorkspaceGroup {
  key: string;
  dir: string;
  label: string;
  tasks: Conversation[];
}

export function Sidebar() {
  const { state, dispatch } = useAppState();
  const currentId = state.currentConversationId;

  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth);
  const [isResizing, setIsResizing] = useState(false);
  const resizeStartX = useRef(0);
  const resizeStartWidth = useRef(SIDEBAR_DEFAULT_WIDTH);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<{
    id: string;
    mode: "task" | "workspace";
  } | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [workspaceMenuKey, setWorkspaceMenuKey] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [collapsedWorkspaces, setCollapsedWorkspaces] = useState<Record<string, boolean>>(
    {}
  );

  const workspaceGroups = useMemo((): WorkspaceGroup[] => {
    const map = new Map<string, WorkspaceGroup>();
    for (const conv of state.conversations) {
      const dir = normPath(conv.workspaceDir);
      const key = dir.toLowerCase() || `orphan:${conv.id}`;
      let group = map.get(key);
      if (!group) {
        group = {
          key,
          dir,
          label: dir ? folderName(dir) : "未绑定目录",
          tasks: [],
        };
        map.set(key, group);
      }
      group.tasks.push(conv);
    }
    for (const g of map.values()) {
      g.tasks.sort((a, b) => b.createdAt - a.createdAt);
    }
    return Array.from(map.values()).sort((a, b) => {
      const at = a.tasks[0]?.createdAt ?? 0;
      const bt = b.tasks[0]?.createdAt ?? 0;
      return bt - at;
    });
  }, [state.conversations]);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // ignore
    }
  }, [collapsed]);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
    } catch {
      // ignore
    }
  }, [sidebarWidth]);

  useEffect(() => {
    if (!isResizing) return;
    const onMove = (e: MouseEvent) => {
      const next = clampSidebarWidth(
        resizeStartWidth.current + (e.clientX - resizeStartX.current)
      );
      setSidebarWidth(next);
    };
    const onUp = () => setIsResizing(false);
    document.body.classList.add("sidebar-resizing");
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      document.body.classList.remove("sidebar-resizing");
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [isResizing]);

  const beginResize = useCallback(
    (e: ReactMouseEvent<HTMLDivElement>) => {
      if (collapsed) {
        setCollapsed(false);
        return;
      }
      e.preventDefault();
      resizeStartX.current = e.clientX;
      resizeStartWidth.current = sidebarWidth;
      setIsResizing(true);
    },
    [collapsed, sidebarWidth]
  );

  useEffect(() => {
    const close = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        !target?.closest(".sidebar-item-menu-wrap") &&
        !target?.closest(".sidebar-workspace-menu-wrap")
      ) {
        setMenuOpenId(null);
        setWorkspaceMenuKey(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const startRename = useCallback((conv: { id: string; title: string }) => {
    setEditingId(conv.id);
    setEditTitle(conv.title);
  }, []);

  const submitRename = useCallback(
    (id: string) => {
      const t = editTitle.trim();
      if (t) dispatch({ type: "SET_CONVERSATION_TITLE", id, title: t });
      setEditingId(null);
      setEditTitle("");
    },
    [editTitle, dispatch]
  );

  const handleCreateWorkspace = useCallback(
    (payload: { name: string; folderPath: string }) => {
      const path = payload.folderPath.trim();
      if (!path) return;
      dispatch({
        type: "NEW_CONVERSATION",
        workspaceDir: path,
        title: payload.name?.trim() || "Agent 任务 1",
      });
      dispatch({ type: "SET_VIEW", view: "session" });
      setCreateOpen(false);
      const modelsDir =
        path.replace(/[/\\]+$/, "") + (path.includes("\\") ? "\\models" : "/models");
      void invoke("bridge_send", {
        cmd: "config_save",
        payload: {
          workspace_dir: path,
          config: { MODEL_OUTPUT_DIR: modelsDir },
        },
      }).catch(() => {});
    },
    [dispatch]
  );

  const handleNewAgentTask = useCallback(
    (workspaceDir?: string | null) => {
      const dir = (workspaceDir || state.workspaceDir || "").trim();
      if (!dir) {
        setCreateOpen(true);
        return;
      }
      dispatch({ type: "NEW_AGENT_TASK", workspaceDir: dir });
      dispatch({ type: "SET_VIEW", view: "session" });
    },
    [dispatch, state.workspaceDir]
  );

  const changeWorkspaceDir = useCallback(
    async (id: string, currentPath?: string | null) => {
      const selected = await open({
        directory: true,
        multiple: false,
        title: "修改工作空间目录",
        defaultPath: currentPath || undefined,
      });
      if (selected == null) return;
      const path = String(selected);
      dispatch({ type: "SET_CONVERSATION_WORKSPACE_DIR", id, path });
      if (id === state.currentConversationId) {
        const modelsDir =
          path.replace(/[/\\]+$/, "") + (path.includes("\\") ? "\\models" : "/models");
        void invoke("bridge_send", {
          cmd: "config_save",
          payload: { config: { MODEL_OUTPUT_DIR: modelsDir } },
        }).catch(() => {});
      }
    },
    [dispatch, state.currentConversationId]
  );

  const confirmDelete = useCallback(async () => {
    if (!deleteConfirm) return;
    const { id, mode } = deleteConfirm;
    const conv = state.conversations.find((c) => c.id === id);
    const dir = normPath(conv?.workspaceDir);
    setDeleteConfirm(null);

    if (mode === "workspace" && dir) {
      const siblings = state.conversations.filter(
        (c) => normPath(c.workspaceDir) === dir
      );
      try {
        await invoke("bridge_send", {
          cmd: "conversation_delete",
          payload: {
            conversation_id: id,
            workspace_dir: dir,
            wipe_workspace: true,
          },
        });
      } catch {
        // 后端失败时仍删本地
      }
      for (const s of siblings) {
        dispatch({ type: "DELETE_CONVERSATION", id: s.id });
      }
      return;
    }

    try {
      await invoke("bridge_send", {
        cmd: "conversation_delete",
        payload: {
          conversation_id: id,
          workspace_dir: conv?.workspaceDir ?? undefined,
          wipe_workspace: false,
        },
      });
    } catch {
      // ignore
    }
    dispatch({ type: "DELETE_CONVERSATION", id });
  }, [deleteConfirm, dispatch, state.conversations]);

  const toggleWorkspaceCollapsed = useCallback((key: string) => {
    setCollapsedWorkspaces((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  return (
    <aside
      className={`sidebar${collapsed ? " sidebar-collapsed" : ""}${
        isResizing ? " is-resizing" : ""
      }`}
      style={{
        width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth,
      }}
    >
      <div className="sidebar-topbar">
        <button
          type="button"
          className={`sidebar-icon-btn${collapsed ? "" : " is-active"}`}
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
        >
          <Icon name={collapsed ? "sidebar-right" : "sidebar-left"} size={16} />
        </button>
      </div>

      <div className="sidebar-actions">
        <button
          type="button"
          className="sidebar-new"
          onClick={() => handleNewAgentTask(state.workspaceDir)}
          title={
            state.workspaceDir
              ? "在当前工作空间新建 Agent 任务"
              : "请先新建工作空间"
          }
          aria-label="新建 Agent 任务"
        >
          <Icon name="add" size={15} />
          {!collapsed && <span>新建 Agent 任务</span>}
        </button>
        <button
          type="button"
          className="sidebar-quiet-btn"
          onClick={() => setCreateOpen(true)}
          title="新建工作空间"
          aria-label="新建工作空间"
        >
          <Icon name="folder-2" size={15} />
          {!collapsed && <span>新建工作空间</span>}
        </button>
      </div>

      {!collapsed && (
        <div className="sidebar-list">
          {state.conversations.length === 0 && (
            <p className="sidebar-empty-hint">
              先新建工作空间，再在同一目录下创建多个 Agent 任务（类似 Cursor）。产物分别写入
              context/models/plans/tasks/&lt;任务id&gt;/。
            </p>
          )}
          {workspaceGroups.map((group) => {
            const isWsCollapsed = Boolean(collapsedWorkspaces[group.key]);
            return (
              <div key={group.key} className="sidebar-workspace">
                <div className="sidebar-workspace-head">
                  <button
                    type="button"
                    className={`sidebar-workspace-toggle${
                      group.tasks.some((t) => t.id === currentId) ? " is-active" : ""
                    }`}
                    onClick={() => toggleWorkspaceCollapsed(group.key)}
                    title={group.dir || group.label}
                  >
                    <Icon
                      name={isWsCollapsed ? "arrow-right-1" : "arrow-down-1"}
                      size={14}
                      className="sidebar-workspace-caret"
                    />
                    <Icon
                      name={isWsCollapsed ? "folder-2" : "folder-open"}
                      size={15}
                      className="sidebar-workspace-folder"
                    />
                    <span className="sidebar-workspace-name">{group.label}</span>
                    <span className="sidebar-workspace-count">{group.tasks.length}</span>
                  </button>
                  <div className="sidebar-workspace-menu-wrap">
                    <button
                      type="button"
                      className="sidebar-item-menu-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setWorkspaceMenuKey((k) =>
                          k === group.key ? null : group.key
                        );
                        setMenuOpenId(null);
                      }}
                      title="工作空间操作"
                      aria-label="工作空间操作"
                    >
                      <Icon name="add" size={14} />
                    </button>
                    {workspaceMenuKey === group.key && (
                      <div className="sidebar-item-menu" role="menu">
                        <button
                          type="button"
                          className="sidebar-item-menu-item"
                          onClick={(e) => {
                            e.stopPropagation();
                            setWorkspaceMenuKey(null);
                            handleNewAgentTask(group.dir);
                          }}
                        >
                          新建 Agent 任务
                        </button>
                        {group.dir && (
                          <button
                            type="button"
                            className="sidebar-item-menu-item"
                            onClick={(e) => {
                              e.stopPropagation();
                              setWorkspaceMenuKey(null);
                              invoke("open_path", { path: group.dir }).catch(() => {});
                            }}
                          >
                            打开目录
                          </button>
                        )}
                        {group.tasks[0] && (
                          <button
                            type="button"
                            className="sidebar-item-menu-item danger"
                            onClick={(e) => {
                              e.stopPropagation();
                              setWorkspaceMenuKey(null);
                              setDeleteConfirm({
                                id: group.tasks[0].id,
                                mode: "workspace",
                              });
                            }}
                          >
                            删除整个工作空间
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                {!isWsCollapsed &&
                  group.tasks.map((conv) => (
                    <div
                      key={conv.id}
                      role="button"
                      tabIndex={0}
                      className={`sidebar-item sidebar-item--task ${
                        conv.id === currentId ? "active" : ""
                      }`}
                      onClick={() => {
                        dispatch({ type: "SWITCH_CONVERSATION", id: conv.id });
                        dispatch({ type: "SET_VIEW", view: "session" });
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          dispatch({ type: "SWITCH_CONVERSATION", id: conv.id });
                          dispatch({ type: "SET_VIEW", view: "session" });
                        }
                      }}
                    >
                      {editingId === conv.id ? (
                        <input
                          type="text"
                          className="sidebar-item-edit"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onBlur={() => submitRename(conv.id)}
                          onKeyDown={(e) => {
                            e.stopPropagation();
                            if (e.key === "Enter") submitRename(conv.id);
                            if (e.key === "Escape") {
                              setEditingId(null);
                              setEditTitle("");
                            }
                          }}
                          onClick={(e) => e.stopPropagation()}
                          aria-label="重命名任务"
                        />
                      ) : (
                        <>
                          <Icon
                            name="record-circle"
                            size={12}
                            className="sidebar-task-dot"
                          />
                          <span className="sidebar-item-title">{conv.title}</span>
                          <div className="sidebar-item-menu-wrap">
                            <button
                              type="button"
                              className="sidebar-item-menu-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                setMenuOpenId((openId) =>
                                  openId === conv.id ? null : conv.id
                                );
                                setWorkspaceMenuKey(null);
                              }}
                              title="任务操作"
                              aria-label="任务操作"
                            >
                              <Icon name="more-circle" size={14} />
                            </button>
                            {menuOpenId === conv.id && (
                              <div className="sidebar-item-menu" role="menu">
                                <button
                                  type="button"
                                  className="sidebar-item-menu-item"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setMenuOpenId(null);
                                    startRename(conv);
                                  }}
                                >
                                  重命名
                                </button>
                                <button
                                  type="button"
                                  className="sidebar-item-menu-item"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setMenuOpenId(null);
                                    void changeWorkspaceDir(conv.id, conv.workspaceDir);
                                  }}
                                >
                                  改绑目录
                                </button>
                                <button
                                  type="button"
                                  className="sidebar-item-menu-item danger"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setMenuOpenId(null);
                                    setDeleteConfirm({ id: conv.id, mode: "task" });
                                  }}
                                >
                                  删除任务
                                </button>
                              </div>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  ))}
              </div>
            );
          })}
        </div>
      )}

      <div className="sidebar-foot">
        <button
          type="button"
          className={`sidebar-settings${state.view === "settings" ? " is-active" : ""}`}
          onClick={() => dispatch({ type: "SET_VIEW", view: "settings" })}
          title="设置"
          aria-label="设置"
          aria-current={state.view === "settings" ? "page" : undefined}
        >
          <Icon name="setting-2" size={16} />
          {!collapsed && <span>设置</span>}
        </button>
      </div>

      <CreateWorkspaceDialog
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onCreate={handleCreateWorkspace}
      />

      <ConfirmDialog
        open={deleteConfirm !== null}
        title={
          deleteConfirm?.mode === "workspace" ? "删除工作空间" : "删除 Agent 任务"
        }
        message={
          deleteConfirm?.mode === "workspace"
            ? "将删除该目录下全部 Agent 任务及其 context/models/plans 产物。工作空间根目录本身不会删除。"
            : "仅删除该任务的对话与 tasks/<id> 下产物，同工作空间其他任务不受影响。"
        }
        confirmLabel="确定"
        cancelLabel="取消"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirm(null)}
      />

      <div
        className="sidebar-resize-handle"
        onMouseDown={beginResize}
        onDoubleClick={() => {
          if (collapsed) {
            setCollapsed(false);
            return;
          }
          setSidebarWidth(SIDEBAR_DEFAULT_WIDTH);
        }}
        title="拖动调整侧边栏宽度（双击恢复默认）"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整侧边栏宽度"
      />
    </aside>
  );
}
