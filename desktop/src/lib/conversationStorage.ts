import type { Conversation } from "./types";
import type { ChatMessage } from "./types";

const CONVERSATIONS_KEY = "mph-agent-conversations";
const MESSAGES_KEY = "mph-agent-messages";
const CURRENT_ID_KEY = "mph-agent-current-conversation-id";

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONVERSATIONS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      return Array.isArray(parsed) ? (parsed as Conversation[]) : [];
    }
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
