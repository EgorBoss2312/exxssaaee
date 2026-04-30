import { NavLink, Outlet, Navigate } from "react-router-dom";
import { useAuth } from "./auth";

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
            <span className="brand-product">база знаний</span>
          </div>
          <nav className="nav-links">
            <NavLink end className={({ isActive }) => (isActive ? "active" : "")} to="/">
              Чат
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
            <div>{user.full_name}</div>
            <div>
              {user.role_name} · {user.email}
            </div>
            <button type="button" className="btn btn-ghost" style={{ marginTop: "0.35rem" }} onClick={logout}>
              Выйти
            </button>
          </div>
        </header>
        <Outlet />
      </div>
    </>
  );
}
