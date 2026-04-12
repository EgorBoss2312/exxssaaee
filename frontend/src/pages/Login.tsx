import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { user, login, loading } = useAuth();
  const [email, setEmail] = useState("admin@edda.local");
  const [password, setPassword] = useState("Admin123!");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
    } catch (e) {
      const msg =
        e instanceof Error ? e.message : "Не удалось войти. Проверьте email и пароль.";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell" style={{ maxWidth: 440 }}>
      <div className="card">
        <h1>Вход</h1>
        <p className="muted">
          Корпоративная база знаний ООО «ЭДДА». Используйте учётную запись,
          выданную администратором.
        </p>
        <form onSubmit={onSubmit}>
          <div style={{ marginBottom: "0.65rem" }}>
            <label className="muted">Email</label>
            <input
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
            />
          </div>
          <div style={{ marginBottom: "0.65rem" }}>
            <label className="muted">Пароль</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          {err && <div className="err">{err}</div>}
          <button className="btn" type="submit" disabled={busy || loading} style={{ marginTop: "0.75rem" }}>
            {busy ? "Вход…" : "Войти"}
          </button>
        </form>
        <p className="muted" style={{ marginTop: "1rem" }}>
          Демо после первого запуска Docker: <code>admin@edda.local</code> /{" "}
          <code>Admin123!</code>
        </p>
      </div>
    </div>
  );
}
