import { useEffect, useState } from "react";
import { apiGet, downloadAuthed } from "../api";
import type { DocumentItem } from "../api";

export default function Knowledge() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [preview, setPreview] = useState<{ title: string; text: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);

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
      <h1>База знаний</h1>
      <p className="muted">
        Список документов, доступных вашей роли. Полный корпус хранится в PostgreSQL; фрагменты
        индексируются для поиска и ответов ИИ.
      </p>
      {err && <div className="err">{err}</div>}
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
                {d.allowed_role_codes.map((c) => (
                  <span key={c} className="badge">
                    {c}
                  </span>
                ))}
              </div>
            </div>
            <div className="row">
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
