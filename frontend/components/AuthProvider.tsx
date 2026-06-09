"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getMe, logout as apiLogout, type SessionUser } from "@/lib/session";
import { AuthModal } from "@/components/AuthModal";

interface SignInOptions {
  onSuccess?: () => void;
}

interface AuthContextValue {
  user: SessionUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  openSignIn: (opts?: SignInOptions) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** First-party auth context. Fetches the current session once on mount and owns
 *  a single sign-in modal. Anonymous play is unaffected — nothing here blocks
 *  rendering and the modal only opens when a user explicitly asks to sign in. */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [onSuccess, setOnSuccess] = useState<(() => void) | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setUser(await getMe());
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const openSignIn = useCallback((opts?: SignInOptions) => {
    setOnSuccess(() => opts?.onSuccess);
    setModalOpen(true);
  }, []);

  const handleAuthed = useCallback(async () => {
    setModalOpen(false);
    await refresh();
    onSuccess?.();
    setOnSuccess(undefined);
  }, [refresh, onSuccess]);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout, openSignIn }}>
      {children}
      <AuthModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onAuthed={handleAuthed}
      />
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
