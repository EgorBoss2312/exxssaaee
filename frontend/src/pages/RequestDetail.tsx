import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost, type RequestDetail, type RequestStatus } from "../api";
import { useAuth } from "../auth";

const STATUS_LABELS: Record<RequestStatus, string> = {
  new: "Новая",
  answered_by_rag: "Авто-ответ RAG",
  escalated: "Эскалирована",
  in_progress: "В работе",
  closed: "Закрыта",
};

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function RequestDetail() {
  const { id } = useParams<{ id: string }>();
  const reqId = Number(id);
  const { user } = useAuth();
  const navigate = useNavigate();
  const [req, setReq] = useState<RequestDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  async function load(showSpinner = true) {
    if (!reqId) return;
    if (showSpinner) setBusy(true);
    try {
      const data = await apiGet<RequestDetail>(`/api/requests/${reqId}`);
      setReq(data);
      setErr(null);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      if (showSpinner) setBusy(false);
    }
  }

  useEffect(() => {
    load();
    const t = window.setInterval(() => load(false), 15_000);
    return () => window.clearInterval(t);
  }, [reqId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [req?.messages.length]);

  async function onSend(e: FormEvent) {
    e.preventDefault();
    if (!req || !text.trim() || sending) return;
    setSending(true);
    setErr(null);
    try {
      await apiPost(`/api/requests/${req.id}/messages`, { content: text.trim() });
      setText("");
      await load(false);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSending(false);
    }
  }

  async function onClaim() {
    if (!req || sending) return;
    setSending(true);
    setErr(null);
    try {
      const upd = await apiPost<RequestDetail>(`/api/requests/${req.id}/claim`, {});
      setReq(upd);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSending(false);
    }
  }

  async function onClose() {
    if (!req || sending) return;
    if (!window.confirm("Закрыть заявку? После закрытия чат станет недоступен для ответа.")) return;
    setSending(true);
    setErr(null);
    try {
      const upd = await apiPost<RequestDetail>(`/api/requests/${req.id}/close`, {});
      setReq(upd);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSending(false);
    }
  }

  if (busy && !req) {
    return (
      <div className="app-shell">
        <p className="muted">Загрузка…</p>
      </div>
    );
  }
  if (!req) {
    return (
      <div className="app-shell">
        <p className="err">{err ?? "Заявка не найдена"}</p>
        <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>
          Назад
        </button>
      </div>
    );
  }

  const isAuthor = req.author.id === user?.id;

  return (
    <div className="app-shell">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.5rem" }}>
        <Link to="/requests" className="btn btn-ghost">
          ← К списку заявок
        </Link>
        <span className={`status-pill status-${req.status}`}>{STATUS_LABELS[req.status]}</span>
      </div>

      <div className="card">
        <h1 style={{ marginTop: 0 }}>{req.title}</h1>
        <div className="request-meta">
          <span><strong>№</strong> {req.id}</span>
          <span><strong>Создана:</strong> {fmtDate(req.created_at)}</span>
          <span>
            <strong>Автор:</strong> {req.author.full_name}
            {req.author.department_name ? ` · ${req.author.department_name}` : ""}
          </span>
          {req.department && (
            <span><strong>Отдел-адресат:</strong> {req.department.name}</span>
          )}
          {req.assignee && (
            <span><strong>Исполнитель:</strong> {req.assignee.full_name}</span>
          )}
          {req.closed_at && <span><strong>Закрыта:</strong> {fmtDate(req.closed_at)}</span>}
        </div>

        <div className="request-body">
          <strong className="muted small">Текст заявки</strong>
          <p style={{ whiteSpace: "pre-wrap", marginTop: "0.4rem" }}>{req.body}</p>
        </div>

        <div className="row" style={{ flexWrap: "wrap", gap: "0.5rem", marginTop: "0.75rem" }}>
          {req.can_claim && (
            <button type="button" className="btn" onClick={onClaim} disabled={sending}>
              Взять в работу
            </button>
          )}
          {req.can_close && (
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={sending}>
              Закрыть заявку
            </button>
          )}
        </div>
        {err && <div className="err">{err}</div>}
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Диалог по заявке</h2>
        {req.messages.length === 0 ? (
          <p className="muted">
            Сообщений ещё нет.{" "}
            {req.status === "escalated" && !req.assignee
              ? "Дождитесь, пока специалист примет заявку в работу."
              : isAuthor
              ? "Напишите уточнение или ожидайте ответа от исполнителя."
              : "Напишите ответ инициатору заявки."}
          </p>
        ) : (
          <div className="req-msg-list">
            {req.messages.map((m) => {
              const mine = m.author.id === user?.id;
              return (
                <div key={m.id} className={`req-msg ${mine ? "mine" : "their"}`}>
                  <div className="req-msg-head">
                    <strong>{m.author.full_name}</strong>
                    {m.author.role_code && (
                      <span className="muted small"> · {m.author.role_code}</span>
                    )}
                    <span className="muted small"> · {fmtDate(m.created_at)}</span>
                  </div>
                  <div className="req-msg-body">{m.content}</div>
                </div>
              );
            })}
            <div ref={bottom} />
          </div>
        )}

        {req.can_reply ? (
          <form onSubmit={onSend} style={{ marginTop: "0.75rem" }}>
            <textarea
              className="input"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Сообщение…"
            />
            <div className="row" style={{ marginTop: "0.5rem" }}>
              <button className="btn" type="submit" disabled={sending || !text.trim()}>
                {sending ? "Отправка…" : "Отправить"}
              </button>
            </div>
          </form>
        ) : (
          <p className="muted small" style={{ marginTop: "0.75rem" }}>
            {req.status === "closed"
              ? "Заявка закрыта — отправка сообщений недоступна."
              : "Сообщения может писать инициатор заявки или исполнитель."}
          </p>
        )}
      </div>
    </div>
  );
}
