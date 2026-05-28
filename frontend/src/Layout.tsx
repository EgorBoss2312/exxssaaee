import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, Navigate, useNavigate } from "react-router-dom";
import { apiGet, apiPost, type NotificationsSummary } from "./api";
import { useAuth } from "./auth";

const POLL_INTERVAL_MS = 20_000;

function relTime(iso: string): string {
  try {
    const t = new Date(iso).getTime();
    const diffSec = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (diffSec < 60) return "только что";
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)} мин назад`;
    if (diffSec < 86_400) return `${Math.floor(diffSec / 3600)} ч назад`;
    return new Date(iso).toLocaleDateString("ru-RU");
  } catch {
    return "";
  }
}

function NotificationsBell() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<NotificationsSummary>({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  async function refresh() {
    try {
      const data = await apiGet<NotificationsSummary>("/api/notifications");
      setSummary(data);
    } catch {
      // тихо — например, сессия истекла; полл повторит
    }
  }

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, [open]);

  async function openNotification(id: number, requestId: number | null | undefined) {
    try {
      await apiPost(`/api/notifications/${id}/read`, {});
    } catch {
      // не критично
    }
    setOpen(false);
    if (requestId) navigate(`/requests/${requestId}`);
    refresh();
  }

  async function markAll() {
    try {
      await apiPost("/api/notifications/read-all", {});
    } catch {
      // не критично
    }
    refresh();
  }

  return (
    <div className="bell-wrap" ref={wrapRef}>
      <button
        type="button"
        className="bell-btn"
        aria-label="Уведомления"
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">🔔</span>
        {summary.unread > 0 && <span className="bell-badge">{summary.unread}</span>}
      </button>
      {open && (
        <div className="bell-dropdown" role="menu">
          <div className="bell-head">
            <strong>Уведомления</strong>
            <button type="button" className="btn btn-ghost btn-sm" onClick={markAll}>
              Прочитать всё
            </button>
          </div>
          {summary.items.length === 0 ? (
            <div className="bell-empty">Пока пусто</div>
          ) : (
            <ul className="bell-list">
              {summary.items.map((n) => (
                <li key={n.id} className={`bell-item${n.is_read ? "" : " unread"}`}>
                  <button
                    type="button"
                    className="bell-item-btn"
                    onClick={() => openNotification(n.id, n.request_id)}
                  >
                    <div className="bell-item-title">{n.title}</div>
                    {n.body && <div className="bell-item-body">{n.body}</div>}
                    <div className="bell-item-meta">{relTime(n.created_at)}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <div className="app-shell">
        <p className="muted">Загрузка…</p>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  const isAdmin = user.role_code === "admin";
  const canUpload = isAdmin || user.role_code === "it";

  return (
    <>
      <div className="app-shell">
        <header className="topnav">
          <div className="brand">
            <span className="brand-company">ООО «ЭДДА»</span>
            <span className="brand-sep" aria-hidden="true" />
            <span className="brand-product">портал внутренних заявок</span>
          </div>
          <nav className="nav-links">
            <NavLink end className={({ isActive }) => (isActive ? "active" : "")} to="/">
              Чат
            </NavLink>
            <NavLink className={({ isActive }) => (isActive ? "active" : "")} to="/requests">
              Заявки
            </NavLink>
            <NavLink className={({ isActive }) => (isActive ? "active" : "")} to="/knowledge">
              База знаний
            </NavLink>
            {canUpload && (
              <NavLink className={({ isActive }) => (isActive ? "active" : "")} to="/upload">
                Загрузка
              </NavLink>
            )}
            {isAdmin && (
              <NavLink className={({ isActive }) => (isActive ? "active" : "")} to="/admin">
                Администрирование
              </NavLink>
            )}
          </nav>
          <div className="userbox">
            <NotificationsBell />
            <div className="user-meta">
              <div>{user.full_name}</div>
              <div>
                {user.role_name} · {user.email}
              </div>
              <button type="button" className="btn btn-ghost" style={{ marginTop: "0.35rem" }} onClick={logout}>
                Выйти
              </button>
            </div>
          </div>
        </header>
        <Outlet />
      </div>
    </>
  );
}
