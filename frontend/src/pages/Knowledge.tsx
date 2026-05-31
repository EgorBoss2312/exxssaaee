import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { apiGet, apiUpload, downloadAuthed } from "../api";
import type { DocumentItem } from "../api";
import { useAuth } from "../auth";

export default function Knowledge() {
  const { user } = useAuth();
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [preview, setPreview] = useState<{ title: string; text: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [replacingId, setReplacingId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const replaceDocRef = useRef<DocumentItem | null>(null);

  const canUpdate = user?.role_code === "admin" || user?.role_code === "it";

  async function load() {
    setErr(null);
    try {
      const d = await apiGet<DocumentItem[]>("/api/documents");
      setDocs(d);
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function startReplace(doc: DocumentItem) {
    replaceDocRef.current = doc;
    fileInputRef.current?.click();
  }

  async function onFilePicked(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    const doc = replaceDocRef.current;
    e.target.value = "";
    replaceDocRef.current = null;
    if (!file || !doc) return;

    setReplacingId(doc.id);
    setErr(null);
    setInfo(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const updated = await apiUpload(`/api/documents/${doc.id}/file`, fd, "PUT") as DocumentItem;
      setDocs((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
      setInfo(`«${updated.title}»: файл заменён на «${updated.original_filename}», индекс обновлён.`);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setReplacingId(null);
    }
  }

  async function openPreview(id: number, title: string) {
    try {
      const p = await apiGet<{ text: string }>(`/api/documents/${id}/preview`);
      setPreview({ title, text: p.text });
    } catch {
      setErr("Не удалось загрузить превью");
    }
  }

  return (
    <div className="app-shell">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.doc,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
        style={{ display: "none" }}
        onChange={(e) => void onFilePicked(e)}
      />
      <h1>База знаний</h1>
      <p className="muted">
        Список документов, доступных вашей роли. Полный корпус хранится в PostgreSQL; фрагменты
        индексируются для поиска и ответов ИИ.
        {canUpdate && (
          <> Кнопка «Обновить» позволяет выбрать новый файл с компьютера и заменить текущую версию документа.</>
        )}
      </p>
      {err && <div className="err">{err}</div>}
      {info && (
        <div
          className="card"
          style={{
            marginTop: "0.75rem",
            marginBottom: "0.75rem",
            padding: "0.65rem 0.85rem",
            borderColor: "var(--accent)",
            fontSize: "0.9rem",
          }}
        >
          {info}
        </div>
      )}
      <div className="doc-list" style={{ marginTop: "1rem" }}>
        {docs.map((d) => (
          <div key={d.id} className="doc-item">
            <div>
              <div style={{ fontWeight: 600 }}>{d.title}</div>
              <div className="muted" style={{ fontSize: "0.85rem" }}>
                {d.original_filename} ·{" "}
                {new Date(d.created_at).toLocaleString("ru-RU")}
              </div>
              <div style={{ marginTop: "0.35rem" }}>
                <span className="muted" style={{ fontSize: "0.75rem", marginRight: "0.35rem" }}>
                  Роли:
                </span>
                {d.allowed_role_codes.map((c) => (
                  <span key={c} className="badge">
                    {c}
                  </span>
                ))}
              </div>
              {(d.tags ?? []).length > 0 && (
                <div style={{ marginTop: "0.35rem" }}>
                  <span className="muted" style={{ fontSize: "0.75rem", marginRight: "0.35rem" }}>
                    Теги:
                  </span>
                  {(d.tags ?? []).map((t) => (
                    <span
                      key={t.id}
                      className="tag-chip"
                      title={t.code}
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
                  ))}
                </div>
              )}
            </div>
            <div className="row">
              {canUpdate && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={replacingId === d.id}
                  onClick={() => startReplace(d)}
                >
                  {replacingId === d.id ? "Загрузка…" : "Обновить"}
                </button>
              )}
              <button type="button" className="btn btn-ghost" onClick={() => openPreview(d.id, d.title)}>
                Превью текста
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => downloadAuthed(`/api/documents/${d.id}/file`, d.original_filename)}
              >
                Скачать
              </button>
            </div>
          </div>
        ))}
        {docs.length === 0 && !err && (
          <p className="muted">Документов пока нет или нет доступа по вашей роли.</p>
        )}
      </div>

      {preview && (
        <div
          role="dialog"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1rem",
            zIndex: 50,
          }}
          onClick={() => setPreview(null)}
        >
          <div
            className="card"
            style={{ maxWidth: 800, maxHeight: "80vh", overflow: "auto", width: "100%" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 style={{ margin: 0 }}>{preview.title}</h2>
              <button type="button" className="btn btn-ghost" onClick={() => setPreview(null)}>
                Закрыть
              </button>
            </div>
            <pre
              className="muted"
              style={{
                whiteSpace: "pre-wrap",
                fontSize: "0.9rem",
                marginTop: "0.75rem",
              }}
            >
              {preview.text || "—"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
