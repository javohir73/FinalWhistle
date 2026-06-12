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
  /** Register work that must complete BEFORE logout revokes the session (e.g.
   *  saving unsynced bracket picks). Returns an unregister function. */
  registerLogoutFlush: (fn: () => Promise<void>) => () => void;
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

  // Monotonic token that invalidates in-flight /me reconciles. A login or
  // logout that completes while a refresh is mid-flight must win over the
  // refresh's result — e.g. a slow pre-login /me 401 (Render cold start)
  // resolving AFTER a successful login must not sign the fresh session out.
  const generationRef = useRef(0);

  const refresh = useCallback(async () => {
    const gen = ++generationRef.current;
    try {
      const me = await getMe(); // user (200) | null (401) | throws (network/cold start)
      if (gen !== generationRef.current) return; // superseded — drop stale result
      setUser(me);
      if (me) saveUserHint(me);
      else clearUserHint();
    } catch {
      // Transient failure — keep whatever we already have (hint/last good user).
    } finally {
      if (gen === generationRef.current) setLoading(false);
    }
  }, []);

  // On mount: paint from the cached hint immediately, then reconcile with /me.
  useEffect(() => {
    const hint = loadUserHint();
    if (hint) setUser(hint);
    void refresh();
  }, [refresh]);

  // Pending-data flushers (e.g. the bracket auto-saver) that must run while the
  // session cookie is still valid — signing out must never lose data.
  const flushersRef = useRef(new Set<() => Promise<void>>());
  const registerLogoutFlush = useCallback((fn: () => Promise<void>) => {
    flushersRef.current.add(fn);
    return () => {
      flushersRef.current.delete(fn);
    };
  }, []);

  const logout = useCallback(async () => {
    generationRef.current++; // an in-flight /me must not resurrect the session UI
    await Promise.allSettled([...flushersRef.current].map((fn) => fn()));
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
    generationRef.current++; // drop any /me reconcile that started pre-login
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
    <AuthContext.Provider
      value={{ user, loading, refresh, logout, openSignIn, registerLogoutFlush }}
    >
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
