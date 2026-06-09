"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import {
  getMe,
  logout as apiLogout,
  loadUserHint,
  saveUserHint,
  clearUserHint,
  type SessionUser,
} from "@/lib/session";
import { AuthModal } from "@/components/AuthModal";
import { AuthToast } from "@/components/AuthToast";

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

/** First-party auth context. The signed-in user is shown instantly on every page
 *  from a cached display hint, then reconciled against /auth/me — so navigating
 *  between pages (or reloading) never flashes back to "Sign in". A transient
 *  /auth/me failure (e.g. backend cold start) does NOT sign the user out. */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const onSuccessRef = useRef<(() => void) | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const me = await getMe(); // user (200) | null (401) | throws (network/cold start)
      setUser(me);
      if (me) saveUserHint(me);
      else clearUserHint();
    } catch {
      // Transient failure — keep whatever we already have (hint/last good user).
    } finally {
      setLoading(false);
    }
  }, []);

  // On mount: paint from the cached hint immediately, then reconcile with /me.
  useEffect(() => {
    const hint = loadUserHint();
    if (hint) setUser(hint);
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await apiLogout();
    clearUserHint();
    setUser(null);
  }, []);

  const openSignIn = useCallback((opts?: SignInOptions) => {
    onSuccessRef.current = opts?.onSuccess;
    setModalOpen(true);
  }, []);

  const handleAuthed = useCallback((authedUser: SessionUser, isNew: boolean) => {
    // Use the user returned by login/register as the source of truth — calling
    // /auth/me here would race the just-set cookie's visibility (Safari/PWA).
    setUser(authedUser);
    saveUserHint(authedUser);
    setLoading(false);
    setModalOpen(false);
    if (isNew) {
      const name = authedUser.display_name?.trim();
      setToast(name ? `Welcome, ${name}! Your account is ready.` : "Your account is ready 🎉");
    }
    onSuccessRef.current?.();
    onSuccessRef.current = undefined;
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout, openSignIn }}>
      {children}
      <AuthModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onAuthed={handleAuthed}
      />
      <AuthToast message={toast} onDone={() => setToast(null)} />
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
