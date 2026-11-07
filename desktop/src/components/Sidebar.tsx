import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useAppState } from "../context/AppStateContext";
import { ConfirmDialog } from "./dialogs/ConfirmDialog";
import { CreateWorkspaceDialog } from "./dialogs/CreateWorkspaceDialog";
import { Icon } from "./Icon";

const SIDEBAR_COLLAPSED_KEY = "mph-agent-sidebar-collapsed";

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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // ignore
    }
  }, [collapsed]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target?.closest(".sidebar-item-menu-wrap")) {
        setMenuOpenId(null);
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
        title: payload.name,
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
    if (!deleteConfirmId) return;
    const id = deleteConfirmId;
    const conv = state.conversations.find((c) => c.id === id);
    setDeleteConfirmId(null);
    try {
      await invoke("bridge_send", {
        cmd: "conversation_delete",
        payload: {
          conversation_id: id,
          workspace_dir: conv?.workspaceDir ?? undefined,
        },
      });
    } catch {
      // 后端失败时仍删除本地会话
    }
    dispatch({ type: "DELETE_CONVERSATION", id });
  }, [deleteConfirmId, dispatch, state.conversations]);

  return (
    <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
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
          onClick={() => setCreateOpen(true)}
          title="新建工作空间"
          aria-label="新建工作空间"
        >
          <Icon name="add" size={15} />
          {!collapsed && <span>新建工作空间</span>}
        </button>
      </div>

      {!collapsed && (
        <div className="sidebar-list">
          {state.conversations.length === 0 && (
            <p className="sidebar-empty-hint">
              选择本地目录新建工作空间。对话、计划与模型会写入其中的 context、models、plans。
            </p>
          )}
          {state.conversations.map((conv) => (
            <div
              key={conv.id}
              role="button"
              tabIndex={0}
              className={`sidebar-item ${conv.id === currentId ? "active" : ""}`}
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
                  aria-label="重命名工作空间"
                />
              ) : (
                <>
                  <span className="sidebar-item-title">{conv.title}</span>
                  <Icon
                    name="arrow-right-01"
                    size={12}
                    className="sidebar-item-chevron"
                  />
                  <div className="sidebar-item-menu-wrap">
                    <button
                      type="button"
                      className="sidebar-item-menu-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setMenuOpenId((openId) =>
                          openId === conv.id ? null : conv.id
                        );
                      }}
                      title="工作空间操作"
                      aria-label="工作空间操作"
                    >
                      <Icon name="add" size={14} />
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
                          修改目录
                        </button>
                        {conv.workspaceDir && (
                          <button
                            type="button"
                            className="sidebar-item-menu-item"
                            onClick={(e) => {
                              e.stopPropagation();
                              setMenuOpenId(null);
                              invoke("open_path", {
                                path: conv.workspaceDir,
                              }).catch(() => {});
                            }}
                          >
                            打开目录
                          </button>
                        )}
                        <button
                          type="button"
                          className="sidebar-item-menu-item danger"
                          onClick={(e) => {
                            e.stopPropagation();
                            setMenuOpenId(null);
                            setDeleteConfirmId(conv.id);
                          }}
                        >
                          删除
                        </button>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          ))}
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
        open={deleteConfirmId !== null}
        title="删除工作空间"
        message="确定删除该工作空间？其 context、models、plans 中的记录与模型文件会一并删除。"
        confirmLabel="确定"
        cancelLabel="取消"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirmId(null)}
      />
    </aside>
  );
}
