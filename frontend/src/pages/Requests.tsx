import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, type RequestItem, type RequestStatus } from "../api";
import { useAuth } from "../auth";

type Tab = "mine" | "inbox";

const STATUS_LABELS: Record<RequestStatus, string> = {
  new: "Новая",
  answered_by_rag: "Авто-ответ RAG",
  escalated: "Эскалирована",
  in_progress: "В работе",
  closed: "Закрыта",
};

function StatusBadge({ status }: { status: RequestStatus }) {
  return <span className={`status-pill status-${status}`}>{STATUS_LABELS[status]}</span>;
}

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

export default function Requests() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("mine");
  const [mine, setMine] = useState<RequestItem[]>([]);
  const [inbox, setInbox] = useState<RequestItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setErr(null);
    try {
      const [m, i] = await Promise.all([
        apiGet<RequestItem[]>("/api/requests/mine"),
        apiGet<RequestItem[]>("/api/requests/inbox"),
      ]);
      setMine(m);
      setInbox(i);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    const id = window.setInterval(load, 25_000);
    return () => window.clearInterval(id);
  }, [user?.id]);

  const items = tab === "mine" ? mine : inbox;

  return (
    <div className="app-shell">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div>
          <h1>Заявки</h1>
          <p className="muted">
            Заявки сотрудников ООО «ЭДДА». Раздел «Мои заявки» — обращения, которые вы создали;
            «Входящие отдела» — эскалированные заявки, адресованные вашему подразделению. После того
            как кто-то из коллег нажимает «Взять в работу», заявка пропадает из общей очереди.
          </p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={load} disabled={busy}>
          Обновить
        </button>
      </div>

      <div className="tabs-row">
        <button
          type="button"
          className={`tab-btn${tab === "mine" ? " active" : ""}`}
          onClick={() => setTab("mine")}
        >
          Мои заявки ({mine.length})
        </button>
        <button
          type="button"
          className={`tab-btn${tab === "inbox" ? " active" : ""}`}
          onClick={() => setTab("inbox")}
        >
          Входящие отдела ({inbox.length})
        </button>
      </div>

      {err && <div className="err">{err}</div>}

      {items.length === 0 ? (
        <div className="card">
          <p className="muted">
            {tab === "mine"
              ? "Вы ещё не создавали заявок. Они создаются автоматически из чата, когда система не может ответить уверенно."
              : "Входящих заявок для вашего отдела сейчас нет."}
          </p>
        </div>
      ) : (
        <div className="request-list">
          {items.map((r) => (
            <Link key={r.id} to={`/requests/${r.id}`} className="request-card">
              <div className="request-card-head">
                <StatusBadge status={r.status} />
                <span className="muted small">№{r.id} · {fmtDate(r.created_at)}</span>
              </div>
              <div className="request-card-title">{r.title}</div>
              <div className="request-card-meta">
                <span>
                  <strong>Автор:</strong> {r.author.full_name}
                  {r.author.department_name ? ` · ${r.author.department_name}` : ""}
                </span>
                {r.department && (
                  <span>
                    <strong>Отдел-адресат:</strong> {r.department.name}
                  </span>
                )}
                {r.assignee && (
                  <span>
                    <strong>Исполнитель:</strong> {r.assignee.full_name}
                  </span>
                )}
                {r.messages_count > 0 && (
                  <span className="muted">сообщений: {r.messages_count}</span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
