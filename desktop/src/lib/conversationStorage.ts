import type { Conversation, ConversationGroup } from "./types";
import type { ChatMessage } from "./types";

const CONVERSATIONS_KEY = "mph-agent-conversations";
const MESSAGES_KEY = "mph-agent-messages";
const CURRENT_ID_KEY = "mph-agent-current-conversation-id";
const GROUPS_KEY = "mph-agent-conversation-groups";
const WORKSPACE_DIR_KEY = "mph-agent-workspace-dir";

function normalizeConversation(raw: unknown): Conversation | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  if (typeof item.id !== "string" || !item.id) return null;
  const title = typeof item.title === "string" && item.title.trim() ? item.title : "Agent 任务";
  const createdAt =
    typeof item.createdAt === "number" && Number.isFinite(item.createdAt)
      ? item.createdAt
      : Date.now();
  const workspaceDir =
    typeof item.workspaceDir === "string" && item.workspaceDir.trim()
      ? item.workspaceDir.trim()
      : null;
  const groupId =
    typeof item.groupId === "string" && item.groupId ? item.groupId : null;
  return {
    id: item.id,
    title,
    createdAt,
    workspaceDir,
    groupId,
  };
}

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONVERSATIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const list = parsed
      .map((item) => normalizeConversation(item))
      .filter((item): item is Conversation => item !== null);

    // 旧版全局工作空间：一次性迁移到当前第一个无路径的会话
    const legacy = loadLegacyWorkspaceDir();
    if (legacy) {
      let migrated = false;
      const next = list.map((conv) => {
        if (!migrated && !conv.workspaceDir) {
          migrated = true;
          return { ...conv, workspaceDir: legacy };
        }
        return conv;
      });
      if (migrated) {
        clearLegacyWorkspaceDir();
        saveConversations(next);
        return next;
      }
    }
    return list;
  } catch (_) {}
  return [];
}

export function saveConversations(conversations: Conversation[]): void {
  try {
    localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(conversations));
  } catch (_) {}
}

export function loadMessagesByConversation(): Record<string, ChatMessage[]> {
  try {
    const raw = localStorage.getItem(MESSAGES_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      return typeof parsed === "object" && parsed !== null
        ? (parsed as Record<string, ChatMessage[]>)
        : {};
    }
  } catch (_) {}
  return {};
}

export function saveMessagesByConversation(
  data: Record<string, ChatMessage[] | unknown[]>
): void {
  try {
    localStorage.setItem(MESSAGES_KEY, JSON.stringify(data));
  } catch (_) {}
}

export function loadCurrentConversationId(): string | null {
  try {
    const raw = localStorage.getItem(CURRENT_ID_KEY);
    return typeof raw === "string" && raw ? raw : null;
  } catch (_) {}
  return null;
}

export function saveCurrentConversationId(id: string): void {
  try {
    localStorage.setItem(CURRENT_ID_KEY, id);
  } catch (_) {}
}

export function loadConversationGroups(): ConversationGroup[] {
  try {
    const raw = localStorage.getItem(GROUPS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      return Array.isArray(parsed) ? (parsed as ConversationGroup[]) : [];
    }
  } catch (_) {}
  return [];
}

export function saveConversationGroups(groups: ConversationGroup[]): void {
  try {
    localStorage.setItem(GROUPS_KEY, JSON.stringify(groups));
  } catch (_) {}
}

function loadLegacyWorkspaceDir(): string | null {
  try {
    const raw = localStorage.getItem(WORKSPACE_DIR_KEY);
    return typeof raw === "string" && raw.trim() ? raw.trim() : null;
  } catch (_) {}
  return null;
}

function clearLegacyWorkspaceDir(): void {
  try {
    localStorage.removeItem(WORKSPACE_DIR_KEY);
  } catch (_) {}
}
