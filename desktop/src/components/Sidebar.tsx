import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { useAppState } from "../context/AppStateContext";
import { ConfirmDialog } from "./dialogs/ConfirmDialog";
import { Icon } from "./Icon";

const SIDEBAR_COLLAPSED_KEY = "mph-agent-sidebar-collapsed";

function formatTime(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function shortPath(path: string): string {
  const parts = path.split(/[/\\]/).filter(Boolean);
  if (parts.length <= 2) return path;
  return `…/${parts.slice(-2).join("/")}`;
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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

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

  const handleDelete = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setDeleteConfirmId(id);
  }, []);

  const pickWorkspace = useCallback(async () => {
    const selected = await open({
      directory: true,
      multiple: false,
      title: "创建或选择工作空间",
      defaultPath: state.workspaceDir || undefined,
    });
    if (selected == null) return;
    const path = String(selected);
    dispatch({ type: "SET_WORKSPACE_DIR", path });
    void invoke("bridge_send", {
      cmd: "config_save",
      payload: { config: { MODEL_OUTPUT_DIR: path } },
    }).catch(() => {});
  }, [dispatch, state.workspaceDir]);

  const confirmDelete = useCallback(async () => {
    if (!deleteConfirmId) return;
    const id = deleteConfirmId;
    setDeleteConfirmId(null);
    try {
      await invoke("bridge_send", {
        cmd: "conversation_delete",
        payload: {
          conversation_id: id,
          workspace_dir: state.workspaceDir ?? undefined,
        },
      });
    } catch {
      // 后端失败时仍删除本地会话
    }
    dispatch({ type: "DELETE_CONVERSATION", id });
  }, [deleteConfirmId, dispatch, state.workspaceDir]);

  return (
    <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
      <div className="sidebar-head">
        <button
          type="button"
          className="sidebar-toggle"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
        >
          <Icon name={collapsed ? "sidebar-right" : "sidebar-left"} size={16} />
        </button>
      </div>
      <button
        type="button"
        className="sidebar-new"
        onClick={() => dispatch({ type: "NEW_CONVERSATION" })}
        title="新建对话"
        aria-label="新建对话"
      >
        {collapsed ? <Icon name="add" size={16} /> : <><Icon name="add" size={14} /> 新建对话</>}
      </button>
      {!collapsed && (
        <>
          <div className="sidebar-workspace">
            <div className="sidebar-section-title">工作空间</div>
            <button
              type="button"
              className="sidebar-workspace-pick"
              onClick={() => void pickWorkspace()}
              title={state.workspaceDir || "创建工作空间"}
            >
              <Icon name="folder-2" size={14} />
              <span>{state.workspaceDir ? shortPath(state.workspaceDir) : "创建工作空间"}</span>
            </button>
            {state.workspaceDir && (
              <button
                type="button"
                className="sidebar-workspace-open"
                onClick={() => invoke("open_path", { path: state.workspaceDir }).catch(() => {})}
              >
                打开目录
              </button>
            )}
            <p className="sidebar-workspace-hint">
              对话记录、计划、过程文件和模型都放在这个目录里。
            </p>
          </div>
          <div className="sidebar-section-title">会话</div>
          <div className="sidebar-list">
            {state.conversations.map((conv) => (
              <div
                key={conv.id}
                role="button"
                tabIndex={0}
                className={`sidebar-item ${conv.id === currentId ? "active" : ""}`}
                onClick={() => dispatch({ type: "SWITCH_CONVERSATION", id: conv.id })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    dispatch({ type: "SWITCH_CONVERSATION", id: conv.id });
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
                    aria-label="重命名对话"
                  />
                ) : (
                  <>
                    <span className="sidebar-item-title">{conv.title}</span>
                    <span className="sidebar-item-time">{formatTime(conv.createdAt)}</span>
                    <div className="sidebar-item-menu-wrap">
                      <button
                        type="button"
                        className="sidebar-item-menu-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpenId((id) => (id === conv.id ? null : conv.id));
                        }}
                        title="会话操作"
                        aria-label="会话操作"
                      >
                        <Icon name="more" size={14} />
                      </button>
                      {menuOpenId === conv.id && (
                        <div className="sidebar-item-menu">
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
                            className="sidebar-item-menu-item danger"
                            onClick={(e) => {
                              setMenuOpenId(null);
                              handleDelete(e, conv.id);
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
        </>
      )}
      {collapsed && (
        <button
          type="button"
          className="sidebar-workspace-icon"
          onClick={() => void pickWorkspace()}
          title={state.workspaceDir || "创建工作空间"}
          aria-label="工作空间"
        >
          <Icon name="folder-2" size={16} />
        </button>
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
      <ConfirmDialog
        open={deleteConfirmId !== null}
        title="删除对话"
        message="确定删除该对话？工作空间里对应的记录和模型文件会一并删除。"
        confirmLabel="确定"
        cancelLabel="取消"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirmId(null)}
      />
    </aside>
  );
}
