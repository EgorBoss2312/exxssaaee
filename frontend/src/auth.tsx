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
import { apiGet } from "./api";

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
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
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
