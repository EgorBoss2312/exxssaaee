import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, type ChatResp } from "../api";
import { useAuth } from "../auth";
import {
  loadChatState,
  newEmptyTab,
  saveChatState,
  truncateChatTitle,
  type ChatMsg,
  type ChatTab,
} from "../chatSessionStorage";

type LlmStatus = { mode: string; model?: string | null; hint?: string | null };

function formatShortTime(ts: number): string {
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(ts));
  } catch {
    return "";
  }
}

export default function Chat() {
  const { user } = useAuth();
  const [chats, setChats] = useState<ChatTab[]>([]);
  const [activeChatId, setActiveChatId] = useState<string>("");
  const [hydrated, setHydrated] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  const active = useMemo(
    () => chats.find((c) => c.id === activeChatId) ?? null,
    [chats, activeChatId],
  );
  const msgs: ChatMsg[] = active?.msgs ?? [];

  useEffect(() => {
    if (!user) return;
    const saved = loadChatState(user.id);
    if (saved && saved.chats.length > 0) {
      setChats(saved.chats);
      const still = saved.chats.some((c) => c.id === saved.activeChatId);
      setActiveChatId(still ? saved.activeChatId : saved.chats[0].id);
    } else {
      const first = newEmptyTab();
      setChats([first]);
      setActiveChatId(first.id);
    }
    setHydrated(true);
  }, [user?.id]);

  useEffect(() => {
    if (!user || !hydrated || chats.length === 0 || !activeChatId) return;
    saveChatState(user.id, chats, activeChatId);
  }, [user, hydrated, chats, activeChatId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, activeChatId]);

  useEffect(() => {
    if (!user) return;
    apiGet<LlmStatus>("/api/meta/llm")
      .then(setLlm)
      .catch(() => setLlm(null));
  }, [user]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!input.trim() || busy || !user || !activeChatId) return;
    const tab = chats.find((c) => c.id === activeChatId);
    if (!tab) return;

    setErr(null);
    const q = input.trim();
    const session_id = tab.backendSessionId;
    setInput("");
    setChats((prev) =>
      prev.map((c) =>
        c.id !== activeChatId
          ? c
          : {
              ...c,
              title: c.msgs.length === 0 ? truncateChatTitle(q) : c.title,
              msgs: [...c.msgs, { role: "user", content: q }],
              updatedAt: Date.now(),
            },
      ),
    );
    setBusy(true);
    try {
      const res = await apiPost<ChatResp>("/api/chat", {
        message: q,
        session_id,
      });
      setChats((prev) =>
        prev.map((c) =>
          c.id !== activeChatId
            ? c
            : {
                ...c,
                backendSessionId: res.session_id,
                msgs: [
                  ...c.msgs,
                  { role: "assistant", content: res.answer, sources: res.sources },
                ],
                updatedAt: Date.now(),
              },
        ),
      );
    } catch (ex) {
      setErr(String(ex));
      setChats((prev) =>
        prev.map((c) =>
          c.id !== activeChatId
            ? c
            : {
                ...c,
                msgs: [
                  ...c.msgs,
                  {
                    role: "assistant",
                    content:
                      "Ошибка запроса к серверу. Убедитесь, что backend запущен и база данных доступна.",
                  },
                ],
                updatedAt: Date.now(),
              },
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    const t = newEmptyTab();
    setChats((c) => [t, ...c]);
    setActiveChatId(t.id);
    setErr(null);
  }

  function selectChat(id: string) {
    if (busy || id === activeChatId) return;
    setActiveChatId(id);
    setInput("");
    setErr(null);
  }

  return (
    <div className="app-shell">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div>
          <h1>Чат с ИИ</h1>
          <p className="muted">
            Ответы формируются по документам, доступным для роли «{user?.role_name}». К источникам
            приводятся фрагменты из базы знаний. История диалогов сохраняется до закрытия вкладки
            браузера.
          </p>
          {llm?.mode === "extractive" && llm.hint && (
            <div className="llm-banner" role="status">
              <div className="llm-banner-title">Режим без языковой модели</div>
              <p className="llm-banner-text">
                В ответ попадают найденные фрагменты документов (без перефразирования нейросетью).{" "}
                {llm.hint}
              </p>
            </div>
          )}
          {llm && llm.mode !== "extractive" && (
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              Модель ответа:{" "}
              <strong>
                {llm.mode === "gemini"
                  ? "Google Gemini"
                  : llm.mode === "openai"
                    ? "OpenAI"
                    : "Ollama"}{" "}
                — {llm.model ?? "—"}
              </strong>
            </p>
          )}
        </div>
        <button type="button" className="btn btn-ghost" onClick={newChat}>
          Новый диалог
        </button>
      </div>

      <div className="chat-layout">
        <aside className="card chat-sidebar" aria-label="Диалоги в этой сессии">
          <h2 style={{ fontSize: "0.9rem", marginBottom: "0.65rem" }}>Диалоги</h2>
          {chats.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`chat-tab-btn${c.id === activeChatId ? " active" : ""}`}
              onClick={() => selectChat(c.id)}
              disabled={busy}
            >
              <div className="chat-tab-title">{c.title}</div>
              <div className="chat-tab-meta">
                {c.msgs.length === 0 ? "Пусто" : `${c.msgs.length} сообщ.`} ·{" "}
                {formatShortTime(c.updatedAt)}
              </div>
            </button>
          ))}
        </aside>

        <div className="card" style={{ minWidth: 0 }}>
          <div style={{ minHeight: 360, maxHeight: "min(62vh, 640px)", overflowY: "auto" }}>
            {msgs.length === 0 && (
              <p className="muted">
                Задайте вопрос по внутренним регламентам и инструкциям. Например: «Как оформить
                отпуск?» или «Что делать при дефекте кромки на линии резки?»
              </p>
            )}
            {msgs.map((m, i) => (
              <div key={`${activeChatId}-${i}`}>
                {m.role === "user" ? (
                  <div className="msg-user">{m.content}</div>
                ) : (
                  <div className="msg-bot">
                    {m.content}
                    {m.sources && m.sources.length > 0 && (
                      <div className="sources">
                        <strong className="muted">Источники:</strong>
                        <ul style={{ margin: "0.35rem 0 0 1rem" }}>
                          {m.sources.map((s, j) => (
                            <li key={j}>
                              {s.document_title} (фрагмент #{s.chunk_index})
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            <div ref={bottom} />
          </div>
          {err && <div className="err">{err}</div>}
          <form onSubmit={onSubmit} style={{ marginTop: "0.75rem" }}>
            <textarea
              className="input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Введите вопрос…"
              rows={3}
            />
            <div className="row" style={{ marginTop: "0.5rem" }}>
              <button className="btn" type="submit" disabled={busy || !active}>
                {busy ? "Отправка…" : "Отправить"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
