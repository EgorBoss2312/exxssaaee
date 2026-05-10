import { FormEvent, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { apiGet, apiUpload, type DocumentTag, type Role } from "../api";
import { useAuth } from "../auth";

function initRoleChecks(r: Role[]): Record<number, boolean> {
  const a: Record<number, boolean> = {};
  r.forEach((x) => {
    if (x.code !== "admin") a[x.id] = false;
  });
  return a;
}

function initTagChecks(tags: DocumentTag[]): Record<number, boolean> {
  const a: Record<number, boolean> = {};
  tags.forEach((t) => {
    a[t.id] = false;
  });
  return a;
}

export default function Upload() {
  const { user } = useAuth();
  const [roles, setRoles] = useState<Role[]>([]);
  const [docTags, setDocTags] = useState<DocumentTag[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docTitle, setDocTitle] = useState("");
  const [allowed, setAllowed] = useState<Record<number, boolean>>({});
  const [tagPick, setTagPick] = useState<Record<number, boolean>>({});

  const can = user && (user.role_code === "admin" || user.role_code === "it");

  useEffect(() => {
    if (!can) return;
    void (async () => {
      try {
        const [r, tg] = await Promise.all([
          apiGet<Role[]>("/api/meta/roles"),
          apiGet<DocumentTag[]>("/api/meta/document-tags"),
        ]);
        setRoles(r);
        setAllowed(initRoleChecks(r));
        setDocTags(tg);
        setTagPick(initTagChecks(tg));
      } catch {
        setErr("Не удалось загрузить списки ролей и тегов");
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
    const tagIds = Object.entries(tagPick)
      .filter(([, v]) => v)
      .map(([k]) => Number(k));

    const fd = new FormData();
    fd.append("title", docTitle.trim());
    fd.append("allowed_role_ids", JSON.stringify(ids));
    fd.append("tag_ids", JSON.stringify(tagIds));
    fd.append("file", file);
    try {
      await apiUpload("/api/documents", fd);
      setFile(null);
      setDocTitle("");
      setAllowed(initRoleChecks(roles));
      setTagPick(initTagChecks(docTags));
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
          {docTags.length > 0 && (
            <div style={{ marginBottom: "0.65rem" }}>
              <label className="muted">Теги документа (необязательно)</label>
              <div className="checkbox-grid">
                {docTags.map((t) => (
                  <label key={t.id}>
                    <input
                      type="checkbox"
                      checked={!!tagPick[t.id]}
                      onChange={(e) =>
                        setTagPick((prev) => ({ ...prev, [t.id]: e.target.checked }))
                      }
                    />
                    <span
                      className="tag-chip tag-chip-inline"
                      style={
                        t.color
                          ? {
                              backgroundColor: t.color,
                              color: "#0f172a",
                              borderColor: t.color,
                            }
                          : undefined
                      }
                    >
                      {t.name}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {docTags.length === 0 && (
            <p className="muted" style={{ marginBottom: "0.65rem" }}>
              Справочник тегов пуст. После применения миграции БД и сидов теги появятся здесь.
            </p>
          )}
          <button className="btn" type="submit">
            Загрузить и проиндексировать
          </button>
        </form>
      </div>
    </div>
  );
}
