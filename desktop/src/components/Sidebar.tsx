import { useState, useEffect, useCallback, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
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
  const [newGroupName, setNewGroupName] = useState("");
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [editingGroupName, setEditingGroupName] = useState("");
  const [draggingConvId, setDraggingConvId] = useState<string | null>(null);
  const [dragOverGroupId, setDragOverGroupId] = useState<string | null>(null);

  const handleDragStart = useCallback(
    (e: React.DragEvent<HTMLDivElement>, convId: string) => {
      setDraggingConvId(convId);
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", convId);
      e.dataTransfer.setData("application/x-mph-conversation-id", convId);
    },
    []
  );

  const getDraggedConversationId = useCallback(
    (e: React.DragEvent) =>
      e.dataTransfer.getData("application/x-mph-conversation-id") ||
      e.dataTransfer.getData("text/plain") ||
      draggingConvId,
    [draggingConvId]
  );

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

  const grouped = useMemo(() => {
    const map = new Map<string, typeof state.conversations>();
    for (const group of state.conversationGroups) {
      map.set(group.id, []);
    }
    const ungrouped = [] as typeof state.conversations;
    for (const conv of state.conversations) {
      if (conv.groupId && map.has(conv.groupId)) {
        map.get(conv.groupId)!.push(conv);
      } else {
        ungrouped.push(conv);
      }
    }
    return { map, ungrouped };
  }, [state.conversations, state.conversationGroups]);

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

  const addGroup = useCallback(() => {
    const name = newGroupName.trim();
    if (!name) return;
    dispatch({ type: "ADD_CONVERSATION_GROUP", name });
    setNewGroupName("");
  }, [newGroupName, dispatch]);

  const submitRenameGroup = useCallback(() => {
    if (!editingGroupId) return;
    const name = editingGroupName.trim();
    if (name) {
      dispatch({ type: "RENAME_CONVERSATION_GROUP", id: editingGroupId, name });
    }
    setEditingGroupId(null);
    setEditingGroupName("");
  }, [editingGroupId, editingGroupName, dispatch]);

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
        <Icon name={collapsed ? "sidebar-right" : "sidebar-left"} size={16} />
      </button>
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
          <div className="sidebar-groups-config">
            <div className="sidebar-section-title">对话集合</div>
            <div className="sidebar-group-create">
              <input
                className="sidebar-group-input"
                placeholder="新集合名称"
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addGroup();
                }}
              />
              <button type="button" className="sidebar-group-add" onClick={addGroup}>
                新建
              </button>
            </div>
          </div>
          <div className="sidebar-list">
            <div
              className={`sidebar-drop-root ${dragOverGroupId === "__ungrouped__" ? "drag-over" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOverGroupId("__ungrouped__");
              }}
              onDragLeave={() => setDragOverGroupId((id) => (id === "__ungrouped__" ? null : id))}
              onDrop={(e) => {
                e.preventDefault();
                const movedId = getDraggedConversationId(e);
                if (movedId) {
                  dispatch({ type: "MOVE_CONVERSATION_TO_GROUP", conversationId: movedId, groupId: null });
                }
                setDraggingConvId(null);
                setDragOverGroupId(null);
              }}
            >
              <div className="sidebar-group-heading">未分组</div>
              {grouped.ungrouped.map((conv) => (
                <div
                  key={conv.id}
                  role="button"
                  tabIndex={0}
                  draggable
                  className={`sidebar-item ${conv.id === currentId ? "active" : ""}`}
                  onDragStart={(e) => handleDragStart(e, conv.id)}
                  onDragEnd={() => {
                    setDraggingConvId(null);
                    setDragOverGroupId(null);
                  }}
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

            {state.conversationGroups.map((group) => (
              <div
                key={group.id}
                className={`sidebar-group-box ${dragOverGroupId === group.id ? "drag-over" : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverGroupId(group.id);
                }}
                onDragLeave={() => setDragOverGroupId((id) => (id === group.id ? null : id))}
                onDrop={(e) => {
                  e.preventDefault();
                  const movedId = getDraggedConversationId(e);
                  if (movedId) {
                    dispatch({ type: "MOVE_CONVERSATION_TO_GROUP", conversationId: movedId, groupId: group.id });
                  }
                  setDraggingConvId(null);
                  setDragOverGroupId(null);
                }}
              >
                <div className="sidebar-group-header">
                  {editingGroupId === group.id ? (
                    <input
                      className="sidebar-group-input inline"
                      value={editingGroupName}
                      onChange={(e) => setEditingGroupName(e.target.value)}
                      onBlur={submitRenameGroup}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") submitRenameGroup();
                        if (e.key === "Escape") {
                          setEditingGroupId(null);
                          setEditingGroupName("");
                        }
                      }}
                    />
                  ) : (
                    <span className="sidebar-group-heading">{group.name}</span>
                  )}
                  <div className="sidebar-group-actions">
                    <button
                      type="button"
                      className="sidebar-group-action-btn"
                      onClick={() => {
                        setEditingGroupId(group.id);
                        setEditingGroupName(group.name);
                      }}
                      title="重命名集合"
                    >
                      <Icon name="edit-2" size={13} />
                    </button>
                    <button
                      type="button"
                      className="sidebar-group-action-btn danger"
                      onClick={() => dispatch({ type: "DELETE_CONVERSATION_GROUP", id: group.id })}
                      title="删除集合"
                    >
                      <Icon name="close-circle" size={13} />
                    </button>
                  </div>
                </div>
                {(grouped.map.get(group.id) ?? []).map((conv) => (
                  <div
                    key={conv.id}
                    role="button"
                    tabIndex={0}
                    draggable
                    className={`sidebar-item ${conv.id === currentId ? "active" : ""}`}
                    onDragStart={(e) => handleDragStart(e, conv.id)}
                    onDragEnd={() => {
                      setDraggingConvId(null);
                      setDragOverGroupId(null);
                    }}
                    onClick={() => dispatch({ type: "SWITCH_CONVERSATION", id: conv.id })}
                  >
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
                  </div>
                ))}
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
