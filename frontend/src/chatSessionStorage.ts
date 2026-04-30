import type { ChatResp } from "./api";

const VERSION = 1 as const;

export type ChatMsg = {
  role: "user" | "assistant";
  content: string;
  sources?: ChatResp["sources"];
};

export type ChatTab = {
  id: string;
  backendSessionId: number | null;
  title: string;
  msgs: ChatMsg[];
  updatedAt: number;
};

export type PersistedChatState = {
  version: typeof VERSION;
  chats: ChatTab[];
  activeChatId: string;
};

function storageKey(userId: number): string {
  return `edda_portal_chat_session_v${VERSION}_${userId}`;
}

function isChatTab(x: unknown): x is ChatTab {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    (o.backendSessionId === null || typeof o.backendSessionId === "number") &&
    typeof o.title === "string" &&
    Array.isArray(o.msgs) &&
    typeof o.updatedAt === "number"
  );
}

export function loadChatState(userId: number): PersistedChatState | null {
  try {
    const raw = sessionStorage.getItem(storageKey(userId));
    if (!raw) return null;
    const data = JSON.parse(raw) as unknown;
    if (!data || typeof data !== "object") return null;
    const o = data as Record<string, unknown>;
    if (o.version !== VERSION || typeof o.activeChatId !== "string" || !Array.isArray(o.chats)) {
      return null;
    }
    if (!o.chats.every(isChatTab)) return null;
    return o as PersistedChatState;
  } catch {
    return null;
  }
}

export function saveChatState(userId: number, chats: ChatTab[], activeChatId: string): void {
  const payload: PersistedChatState = {
    version: VERSION,
    chats,
    activeChatId,
  };
  try {
    sessionStorage.setItem(storageKey(userId), JSON.stringify(payload));
  } catch {
    // квота или приватный режим
  }
}

export function truncateChatTitle(text: string, maxLen = 52): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= maxLen) return t || "Новый диалог";
  return `${t.slice(0, maxLen - 1)}…`;
}

export function newEmptyTab(): ChatTab {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `tab_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  return {
    id,
    backendSessionId: null,
    title: "Новый диалог",
    msgs: [],
    updatedAt: Date.now(),
  };
}
