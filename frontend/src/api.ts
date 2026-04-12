function stripTrailingSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

/** Путь приложения из Vite (`base` в vite.config), без хвостового `/`. Пусто = корень сайта. */
function vitePublicBasePath(): string {
  const b = import.meta.env.BASE_URL ?? "/";
  if (b === "/" || b === "") return "";
  const norm = b.startsWith("/") ? b : `/${b}`;
  return stripTrailingSlash(norm);
}

/**
 * Явная база API (другой домен или абсолютный URL), без завершающего `/`.
 * Приоритет: meta → window → VITE_API_BASE_URL.
 */
function configuredApiBase(): string {
  if (typeof document !== "undefined") {
    const meta = document
      .querySelector('meta[name="edda-api-base"]')
      ?.getAttribute("content");
    if (meta && meta.trim() !== "") return stripTrailingSlash(meta.trim());
  }
  if (typeof window !== "undefined") {
    const w = window as Window & { __EDDA_API_BASE__?: unknown };
    const injected = w.__EDDA_API_BASE__;
    if (typeof injected === "string" && injected.trim() !== "") {
      return stripTrailingSlash(injected.trim());
    }
  }
  const env = import.meta.env.VITE_API_BASE_URL;
  if (typeof env === "string" && env.trim() !== "") {
    return stripTrailingSlash(env.trim());
  }
  return "";
}

/**
 * URL для fetch к бэкенду: учитывает другой хост (VITE/meta), подкаталог SPA (`import.meta.env.BASE_URL`)
 * и обычный случай «тот же origin» (относительный путь `/api/...`).
 */
export function resolveApiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const custom = configuredApiBase();
  if (custom !== "") {
    return `${custom}${p}`;
  }
  const sub = vitePublicBasePath();
  if (sub !== "" && typeof window !== "undefined") {
    return `${window.location.origin}${sub}${p}`;
  }
  return p;
}

/** Только явно заданная база (без подкаталога Vite) — для подсказок. */
export function getApiBase(): string {
  return configuredApiBase();
}

function authHeader(): HeadersInit {
  const t = localStorage.getItem("token");
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(resolveApiUrl(path), { headers: { ...authHeader() } });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(resolveApiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(resolveApiUrl(path), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

export async function apiUpload(
  path: string,
  form: FormData,
): Promise<unknown> {
  const r = await fetch(resolveApiUrl(path), {
    method: "POST",
    headers: { ...authHeader() },
    body: form,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiDelete(path: string): Promise<void> {
  const r = await fetch(resolveApiUrl(path), {
    method: "DELETE",
    headers: { ...authHeader() },
  });
  if (!r.ok) throw new Error(await r.text());
}

export async function downloadAuthed(path: string, filename: string): Promise<void> {
  const r = await fetch(resolveApiUrl(path), { headers: { ...authHeader() } });
  if (!r.ok) throw new Error(await r.text());
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export type UserMe = {
  id: number;
  email: string;
  full_name: string;
  role_id: number;
  role_code: string;
  role_name: string;
  is_active: boolean;
};

export type Role = {
  id: number;
  code: string;
  name: string;
  description?: string | null;
};

export type DocumentItem = {
  id: number;
  title: string;
  original_filename: string;
  mime_type: string | null;
  created_at: string;
  uploaded_by_name?: string | null;
  allowed_role_codes: string[];
};

export type ChatResp = {
  answer: string;
  sources: {
    document_id: number;
    document_title: string;
    chunk_index: number;
    excerpt: string;
  }[];
  session_id: number;
};
