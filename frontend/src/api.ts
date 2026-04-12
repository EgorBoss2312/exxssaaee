function stripTrailingSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

/**
 * База URL бэкенда без завершающего `/`.
 * Пустая строка — запросы на тот же origin (один контейнер, nginx с общим хостом).
 * На деплое с разными доменами: при сборке `VITE_API_BASE_URL`, либо в index.html до бандла:
 * `window.__EDDA_API_BASE__ = "https://api.ваш-домен.ru";`
 */
export function getApiBase(): string {
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

function authHeader(): HeadersInit {
  const t = localStorage.getItem("token");
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${getApiBase()}${path}`, { headers: { ...authHeader() } });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${getApiBase()}${path}`, {
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
  const r = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: { ...authHeader() },
    body: form,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiDelete(path: string): Promise<void> {
  const r = await fetch(`${getApiBase()}${path}`, {
    method: "DELETE",
    headers: { ...authHeader() },
  });
  if (!r.ok) throw new Error(await r.text());
}

export async function downloadAuthed(path: string, filename: string): Promise<void> {
  const r = await fetch(`${getApiBase()}${path}`, { headers: { ...authHeader() } });
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
