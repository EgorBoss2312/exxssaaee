import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { UserMe } from "./api";
import { apiGet, resolveApiUrl } from "./api";

const LOGIN_UNAVAILABLE =
  "Сервер API не отвечает. Откройте DevTools → Network: виден ли запрос к /api/auth/login, статус (blocked/CORS/mixed content). " +
  "Проверьте прокси nginx: /api должен идти на Uvicorn (см. deploy/nginx-example.conf). " +
  "Разные домены: VITE_API_BASE_URL или meta edda-api-base; на бэкенде CORS_ORIGINS=https://ваш-сайт. " +
  "Подкаталог SPA: задайте base в vite.config. Локально: backend на :8000, http://127.0.0.1:8000.";

type AuthState = {
  user: UserMe | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem("token"),
  );
  const [user, setUser] = useState<UserMe | null>(null);
  const [loading, setLoading] = useState(!!token);

  const refresh = useCallback(async () => {
    const t = localStorage.getItem("token");
    if (!t) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await apiGet<UserMe>("/api/auth/me");
      setUser(me);
    } catch {
      localStorage.removeItem("token");
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    let r: Response;
    try {
      r = await fetch(resolveApiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      throw new Error(LOGIN_UNAVAILABLE);
    }
    if (!r.ok) {
      let detail = "Неверный логин или пароль";
      try {
        const j = (await r.json()) as {
          detail?: string | Array<{ msg?: string } | string>;
        };
        if (typeof j.detail === "string") {
          detail = j.detail;
        } else if (Array.isArray(j.detail) && j.detail.length) {
          const first = j.detail[0];
          if (typeof first === "string") detail = first;
          else if (first && typeof first === "object" && "msg" in first && first.msg)
            detail = String(first.msg);
        }
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    const data = (await r.json()) as { access_token: string };
    localStorage.setItem("token", data.access_token);
    setToken(data.access_token);
    await refresh();
  }, [refresh]);

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    setToken(null);
    setUser(null);
  }, []);

  const v = useMemo(
    () => ({ user, token, loading, login, logout, refresh }),
    [user, token, loading, login, logout, refresh],
  );

  return <Ctx.Provider value={v}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const x = useContext(Ctx);
  if (!x) throw new Error("AuthProvider missing");
  return x;
}
