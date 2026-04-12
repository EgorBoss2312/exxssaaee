import { FormEvent, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { apiGet, apiPatch, apiPost, type Role, type UserMe } from "../api";
import { useAuth } from "../auth";

export default function Admin() {
  const { user } = useAuth();
  const [roles, setRoles] = useState<Role[]>([]);
  const [users, setUsers] = useState<UserMe[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newPass, setNewPass] = useState("");
  const [newRoleId, setNewRoleId] = useState<number>(1);

  const isAdmin = user?.role_code === "admin";

  async function load() {
    setErr(null);
    try {
      const [r, u] = await Promise.all([
        apiGet<Role[]>("/api/meta/roles"),
        apiGet<UserMe[]>("/api/admin/users"),
      ]);
      setRoles(r);
      setUsers(u);
      if (r.length) setNewRoleId((id) => (r.some((x) => x.id === id) ? id : r[0].id));
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    if (!isAdmin) return;
    void load();
  }, [isAdmin]);

  async function createUser(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await apiPost<UserMe>("/api/admin/users", {
        email: newEmail,
        password: newPass,
        full_name: newName,
        role_id: newRoleId,
      });
      setNewEmail("");
      setNewName("");
      setNewPass("");
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function toggleActive(u: UserMe) {
    try {
      await apiPatch(`/api/admin/users/${u.id}`, { is_active: !u.is_active });
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  if (!user) return null;
  if (!isAdmin) return <Navigate to="/" replace />;

  return (
    <div className="app-shell">
      <h1>Администрирование</h1>
      <p className="muted">Создание пользователей и назначение ролей (структура подразделений).</p>
      {err && <div className="err">{err}</div>}

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>Пользователи</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Email</th>
              <th>ФИО</th>
              <th>Роль</th>
              <th>Статус</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td>{u.full_name}</td>
                <td>{u.role_name}</td>
                <td>{u.is_active ? "активен" : "заблокирован"}</td>
                <td>
                  {u.role_code !== "admin" && (
                    <button type="button" className="btn btn-ghost" onClick={() => toggleActive(u)}>
                      {u.is_active ? "Заблокировать" : "Разблокировать"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <h2 style={{ marginTop: "1.25rem" }}>Новый пользователь</h2>
        <form onSubmit={createUser} className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label className="muted">Email</label>
            <input className="input" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label className="muted">ФИО</label>
            <input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} />
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <label className="muted">Пароль</label>
            <input
              className="input"
              type="password"
              value={newPass}
              onChange={(e) => setNewPass(e.target.value)}
            />
          </div>
          <div style={{ minWidth: 200 }}>
            <label className="muted">Роль</label>
            <select
              className="input"
              value={newRoleId}
              onChange={(e) => setNewRoleId(Number(e.target.value))}
            >
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
          <button className="btn" type="submit">
            Создать
          </button>
        </form>
      </div>
    </div>
  );
}
