import { FormEvent, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, type ChatResp } from "../api";
import { useAuth } from "../auth";

type LlmStatus = { mode: string; model?: string | null; hint?: string | null };

type Msg = { role: "user" | "assistant"; content: string; sources?: ChatResp["sources"] };

export default function Chat() {
  const { user } = useAuth();
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  useEffect(() => {
    if (!user) return;
    apiGet<LlmStatus>("/api/meta/llm")
      .then(setLlm)
      .catch(() => setLlm(null));
  }, [user]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!input.trim() || busy) return;
    setErr(null);
    const q = input.trim();
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setBusy(true);
    try {
      const res = await apiPost<ChatResp>("/api/chat", {
        message: q,
        session_id: sessionId,
      });
      setSessionId(res.session_id);
      setMsgs((m) => [
        ...m,
        { role: "assistant", content: res.answer, sources: res.sources },
      ]);
    } catch (ex) {
      setErr(String(ex));
      setMsgs((m) => [
        ...m,
        {
          role: "assistant",
          content:
            "Ошибка запроса к серверу. Убедитесь, что backend запущен и база данных доступна.",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    setSessionId(null);
    setMsgs([]);
    setErr(null);
  }

  return (
    <div className="app-shell">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div>
          <h1>Чат с ИИ</h1>
          <p className="muted">
            Ответы формируются по документам, доступным для роли «{user?.role_name}». К источникам
            приводятся фрагменты из базы знаний.
          </p>
          {llm?.mode === "extractive" && llm.hint && (
            <p className="muted" style={{ marginTop: "0.35rem", color: "#fbbf24" }}>
              Режим без LLM: ответы — вставки из найденных фрагментов. {llm.hint}
            </p>
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

      <div className="card">
        <div style={{ minHeight: 360, maxHeight: "min(62vh, 640px)", overflowY: "auto" }}>
          {msgs.length === 0 && (
            <p className="muted">
              Задайте вопрос по внутренним регламентам и инструкциям. Например: «Как оформить
              отпуск?» или «Что делать при дефекте кромки на линии резки?»
            </p>
          )}
          {msgs.map((m, i) => (
            <div key={i}>
              {m.role === "user" ? (
                <div className="msg-user">{m.content}</div>
              ) : (
                <div className="msg-bot">
                  {m.content}
                  {m.sources && m.sources.length > 0 && (
                    <div className="sources">
                      <strong style={{ color: "#94a3b8" }}>Источники:</strong>
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
            <button className="btn" type="submit" disabled={busy}>
              {busy ? "Отправка…" : "Отправить"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
