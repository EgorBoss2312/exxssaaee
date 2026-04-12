import { FormEvent, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { apiGet, apiUpload, type Role } from "../api";
import { useAuth } from "../auth";

export default function Upload() {
  const { user } = useAuth();
  const [roles, setRoles] = useState<Role[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docTitle, setDocTitle] = useState("");
  const [allowed, setAllowed] = useState<Record<number, boolean>>({});

  const can = user && (user.role_code === "admin" || user.role_code === "it");

  useEffect(() => {
    if (!can) return;
    void (async () => {
      try {
        const r = await apiGet<Role[]>("/api/meta/roles");
        setRoles(r);
        const a: Record<number, boolean> = {};
        r.forEach((x) => {
          if (x.code !== "admin") a[x.id] = false;
        });
        setAllowed(a);
      } catch {
        setErr("Не удалось загрузить список ролей");
      }
    })();
  }, [can]);

  if (!user) return null;
  if (!can) return <Navigate to="/" replace />;

  async function uploadDoc(e: FormEvent) {
    e.preventDefault();
    if (!file || !docTitle.trim()) return;
    const ids = Object.entries(allowed)
      .filter(([, v]) => v)
      .map(([k]) => Number(k));
    if (ids.length === 0) {
      setErr("Выберите хотя бы одну роль для доступа к документу.");
      return;
    }
    setErr(null);
    const fd = new FormData();
    fd.append("title", docTitle.trim());
    fd.append("allowed_role_ids", JSON.stringify(ids));
    fd.append("file", file);
    try {
      await apiUpload("/api/documents", fd);
      setFile(null);
      setDocTitle("");
      setAllowed({});
      alert("Документ загружен и проиндексирован.");
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <div className="app-shell">
      <h1>Загрузка документов</h1>
      <p className="muted">
        Добавление файлов в корпоративную базу знаний. Текст извлекается, разбивается на фрагменты и
        индексируется для поиска и чата.
      </p>
      {err && <div className="err">{err}</div>}
      <div className="card" style={{ marginTop: "1rem" }}>
        <form onSubmit={uploadDoc}>
          <div style={{ marginBottom: "0.65rem" }}>
            <label className="muted">Название</label>
            <input className="input" value={docTitle} onChange={(e) => setDocTitle(e.target.value)} />
          </div>
          <div style={{ marginBottom: "0.65rem" }}>
            <label className="muted">Файл (PDF, DOCX, TXT)</label>
            <input
              className="input"
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div style={{ marginBottom: "0.65rem" }}>
            <label className="muted">Какие роли видят документ</label>
            <div className="checkbox-grid">
              {roles
                .filter((r) => r.code !== "admin")
                .map((r) => (
                  <label key={r.id}>
                    <input
                      type="checkbox"
                      checked={!!allowed[r.id]}
                      onChange={(e) =>
                        setAllowed((prev) => ({ ...prev, [r.id]: e.target.checked }))
                      }
                    />
                    {r.name}
                  </label>
                ))}
            </div>
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              Администратор всегда видит все документы.
            </p>
          </div>
          <button className="btn" type="submit">
            Загрузить и проиндексировать
          </button>
        </form>
      </div>
    </div>
  );
}
