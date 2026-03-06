import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useAppState } from "../context/AppStateContext";
import { ConfirmDialog } from "./dialogs/ConfirmDialog";

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

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // ignore
    }
  }, [collapsed]);

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

  const handleDelete = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      setDeleteConfirmId(id);
    },
    []
  );

  const confirmDelete = useCallback(async () => {
    if (!deleteConfirmId) return;
    const id = deleteConfirmId;
    setDeleteConfirmId(null);
    try {
      await invoke("bridge_send", {
        cmd: "conversation_delete",
        payload: { conversation_id: id },
      });
    } catch {
      // 后端失败时仍删除本地会话
    }
    dispatch({ type: "DELETE_CONVERSATION", id });
  }, [deleteConfirmId, dispatch]);

  return (
    <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
      <button
        type="button"
        className="sidebar-toggle"
        onClick={() => setCollapsed((c) => !c)}
        title={collapsed ? "展开侧边栏" : "收起侧边栏"}
        aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
      >
        {collapsed ? "▶" : "◀"}
      </button>
      {!collapsed && (
        <>
          <button
            type="button"
            className="sidebar-new"
            onClick={() => dispatch({ type: "NEW_CONVERSATION" })}
            title="新建对话"
          >
            + 新建对话
          </button>
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
                    <span
                      className="sidebar-item-title"
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        startRename(conv);
                      }}
                      title="双击重命名"
                    >
                      {conv.title}
                    </span>
                    <span className="sidebar-item-time">{formatTime(conv.createdAt)}</span>
                    <button
                      type="button"
                      className="sidebar-item-delete"
                      onClick={(e) => handleDelete(e, conv.id)}
                      title="删除对话"
                      aria-label="删除对话"
                    >
                      ×
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>
        </>
      )}
      <ConfirmDialog
        open={deleteConfirmId !== null}
        title="删除对话"
        message="确定删除该对话？对话记录与对应的 COMSOL 模型文件将一并删除且无法恢复。"
        confirmLabel="确定"
        cancelLabel="取消"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirmId(null)}
      />
    </aside>
  );
}
