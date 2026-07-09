"use client";

import { useEffect, useRef, useState } from "react";
import {
  login,
  register,
  requestPasswordReset,
  friendlyAuthError,
  type SessionUser,
} from "@/lib/session";
import { trackEvent } from "@/lib/analytics";

type Mode = "signin" | "signup";

/** Email + password sign-in / create-account modal. No social logins, no email
 *  verification yet (so the reset notice below is honest). Calls onAuthed after a
 *  successful sign-in so the caller can refresh state + sync the local bracket. */
export function AuthModal({
  open,
  onClose,
  onAuthed,
  initialMode = "signin",
}: {
  open: boolean;
  onClose: () => void;
  onAuthed: (user: SessionUser, isNew: boolean) => void;
  /** Tab the modal opens on — e.g. a "Create free account" CTA should land
   *  straight on the sign-up tab instead of the default sign-in tab. */
  initialMode?: Mode;
}) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [forgot, setForgot] = useState(false); // "forgot password" sub-view
  const [resetSent, setResetSent] = useState(false);
  // Inline, themed replacements for native browser validation tooltips (which
  // are unstyled and off-theme) — set on empty submit, cleared as the user
  // fixes each field.
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const firstField = useRef<HTMLInputElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);

  // Every open resets to the caller's requested tab (sign-in by default): the
  // nav button says "Sign in" and expects that tab, and a tab left on "Create
  // account" from a previous user makes existing users accidentally
  // re-register ("account already exists"). A CTA like "Create free account"
  // passes initialMode="signup" to land straight on that tab instead.
  useEffect(() => {
    if (open) {
      setMode(initialMode);
      setForgot(false);
      setResetSent(false);
    }
  }, [open, initialMode]);

  useEffect(() => {
    if (open) {
      setError(null);
      setPassword("");
      setShowPassword(false);
      setFieldErrors({});
      setTimeout(() => firstField.current?.focus(), 0);
    }
  }, [open, mode]);

  // Return focus to whatever opened the modal once it closes.
  useEffect(() => {
    if (open) {
      restoreFocus.current = document.activeElement as HTMLElement | null;
    } else {
      restoreFocus.current?.focus?.();
      restoreFocus.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      // Keep Tab inside the dialog (basic focus trap).
      if (e.key === "Tab" && card.current) {
        const focusables = card.current.querySelectorAll<HTMLElement>(
          'button, input, [href], [tabindex]:not([tabindex="-1"])',
        );
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        const outside = !card.current.contains(active);
        if (e.shiftKey && (active === first || outside)) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && (active === last || outside)) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // When connectivity returns, clear a stale offline message so the user can
  // retry without a leftover error (other errors are left as-is).
  useEffect(() => {
    if (!open) return;
    const onOnline = () => setError((prev) => (prev && /offline/i.test(prev) ? null : prev));
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [open]);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    // The form carries noValidate (native tooltips are unstyled/off-theme), so
    // empty required fields don't block submission on their own — check them
    // here and surface themed inline errors instead.
    const nextFieldErrors: { email?: string; password?: string } = {};
    if (!email.trim()) nextFieldErrors.email = "Email is required.";
    if (!password) {
      nextFieldErrors.password = "Password is required.";
    } else if (password.length < 8) {
      // Client-side stand-in for the removed native minLength=8 check (now
      // inert under noValidate) — same wording/tone as the backend's
      // weak_password message (backend/app/api/auth.py) so the copy matches
      // whichever side actually enforces it. Applies in both modes, same as
      // the old native attribute did.
      nextFieldErrors.password = "Password must be at least 8 characters.";
    }
    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) return;
    // Don't fire a guaranteed-to-fail request when the device is offline — say so
    // and let the online listener (below) clear it when connectivity returns.
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setError(friendlyAuthError(null, { offline: true }));
      return;
    }
    setBusy(true);
    setError(null);
    // The free-tier backend sleeps when idle; the first request after a quiet
    // spell can take tens of seconds. Past ~4s, say so instead of looking hung.
    const slowTimer = setTimeout(() => setSlow(true), 4000);
    try {
      let user: SessionUser;
      if (mode === "signup") {
        user = await register(email.trim(), password, name.trim() || undefined);
        trackEvent("signup");
      } else {
        user = await login(email.trim(), password);
        trackEvent("login");
      }
      // Pass the authoritative user straight through — don't rely on an immediate
      // /auth/me, which can race the just-set cookie's visibility (Safari/PWA).
      onAuthed(user, mode === "signup");
      // Clear every field once the account is in: on a shared device the next
      // person to open this modal must not inherit this user's details.
      setEmail("");
      setPassword("");
      setName("");
    } catch (err) {
      setError(
        friendlyAuthError(err, {
          offline: typeof navigator !== "undefined" && navigator.onLine === false,
        }),
      );
    } finally {
      clearTimeout(slowTimer);
      setSlow(false);
      setBusy(false);
    }
  };

  const submitForgot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setError(friendlyAuthError(null, { offline: true }));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await requestPasswordReset(email.trim());
      trackEvent("password_reset_requested");
      // Enumeration-safe: the backend resolves 200 for any email, so we always
      // show the same neutral confirmation (never "no such account").
      setResetSent(true);
    } catch (err) {
      // Only a real failure (rate limit / offline / server) surfaces — these
      // leak nothing about whether the account exists.
      setError(
        friendlyAuthError(err, {
          offline: typeof navigator !== "undefined" && navigator.onLine === false,
        }),
      );
    } finally {
      setBusy(false);
    }
  };

  const tab = (m: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === m}
      aria-label={m === "signin" ? "Switch to sign in" : "Switch to create account"}
      onClick={() => setMode(m)}
      className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold transition ${
        mode === m ? "bg-surface text-foreground shadow-sm" : "text-muted hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );

  const field =
    "w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground outline-none transition focus:border-win";

  const forgotView = resetSent ? (
    <div className="space-y-4">
      <p className="text-sm text-foreground">
        If an account exists for{" "}
        <span className="font-semibold">{email.trim() || "that email"}</span>, we just
        sent a reset link. Check your inbox (and your spam folder).
      </p>
      <button
        type="button"
        onClick={() => {
          setForgot(false);
          setResetSent(false);
          setError(null);
        }}
        className="w-full rounded-xl bg-win px-4 py-3 text-sm font-bold text-pitch transition hover:brightness-110"
      >
        Back to sign in
      </button>
    </div>
  ) : (
    <form onSubmit={submitForgot} className="space-y-3">
      <p className="text-sm text-muted">
        Enter your email and we&rsquo;ll send a link to reset your password.
      </p>
      <input
        ref={firstField}
        type="email"
        required
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email address"
        aria-label="Email address"
        className={field}
      />
      {error && <p className="text-sm text-loss">{error}</p>}
      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-xl bg-win px-4 py-3 text-sm font-bold text-pitch transition hover:brightness-110 disabled:opacity-50"
      >
        {busy ? "Please wait…" : "Send reset link"}
      </button>
      <button
        type="button"
        onClick={() => {
          setForgot(false);
          setError(null);
        }}
        className="block w-full text-center text-xs font-medium text-muted underline-offset-2 transition hover:text-foreground hover:underline"
      >
        Back to sign in
      </button>
    </form>
  );

  return (
    <div
      className="fixed inset-0 z-[100] grid place-items-end bg-pitch/45 backdrop-blur-sm sm:place-items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={forgot ? "Reset password" : mode === "signup" ? "Create account" : "Sign in"}
      onClick={onClose}
    >
      <div
        ref={card}
        className="glass w-full max-w-sm rounded-t-3xl px-5 pb-7 pt-3 sm:rounded-2xl sm:p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Grab handle (mobile bottom-sheet affordance) */}
        <div aria-hidden className="mx-auto mb-4 h-1 w-10 rounded-full bg-border sm:hidden" />
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-lg font-extrabold tracking-tight">
            {forgot
              ? "Reset your password"
              : mode === "signup"
                ? "Create your account"
                : "Welcome back"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="grid h-9 w-9 place-items-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-foreground"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        {forgot ? forgotView : (
        <>
        <div
          role="tablist"
          aria-label="Authentication mode"
          className="mb-4 flex gap-1 rounded-xl bg-surface-2 p-1"
        >
          {tab("signin", "Sign in")}
          {tab("signup", "Create account")}
        </div>

        <form onSubmit={submit} noValidate className="space-y-3">
          {mode === "signup" && (
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={40}
              placeholder="Display name (optional)"
              aria-label="Display name"
              className={field}
            />
          )}
          <div>
            <input
              ref={firstField}
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                if (fieldErrors.email) setFieldErrors((f) => ({ ...f, email: undefined }));
              }}
              placeholder="Email address"
              aria-label="Email address"
              aria-invalid={fieldErrors.email ? true : undefined}
              aria-describedby={fieldErrors.email ? "auth-email-error" : undefined}
              className={field}
            />
            {fieldErrors.email && (
              <p id="auth-email-error" className="mt-1 text-xs text-loss">
                {fieldErrors.email}
              </p>
            )}
          </div>
          <div>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                required
                minLength={8}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (fieldErrors.password) setFieldErrors((f) => ({ ...f, password: undefined }));
                }}
                placeholder="Password (8+ characters)"
                aria-label="Password"
                aria-invalid={fieldErrors.password ? true : undefined}
                aria-describedby={fieldErrors.password ? "auth-password-error" : undefined}
                className={`${field} pr-11`}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-lg text-muted transition hover:text-foreground"
              >
                {showPassword ? (
                  <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M3 3l18 18" />
                    <path d="M10.6 10.6a3 3 0 0 0 4.2 4.2" />
                    <path d="M9.9 5.2A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.9 3.7M6.2 6.2A17.5 17.5 0 0 0 2 12s3.5 7 10 7a10.4 10.4 0 0 0 3.4-.6" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
            {fieldErrors.password && (
              <p id="auth-password-error" className="mt-1 text-xs text-loss">
                {fieldErrors.password}
              </p>
            )}
          </div>

          {mode === "signin" && (
            <button
              type="button"
              onClick={() => {
                setForgot(true);
                setError(null);
                setResetSent(false);
              }}
              className="block text-xs font-semibold text-lime-deep underline-offset-2 hover:underline"
            >
              Forgot password?
            </button>
          )}

          {error && <p className="text-sm text-loss">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-xl bg-win px-4 py-3 text-sm font-bold text-pitch transition hover:brightness-110 disabled:opacity-50"
          >
            {busy ? "Please wait…" : mode === "signup" ? "Create account" : "Sign in"}
          </button>

          {busy && slow && (
            <p className="text-center text-xs text-muted" role="status">
              Still working — waking the match server after a quiet spell can take
              up to a minute. Hang tight.
            </p>
          )}
        </form>

        <p className="mt-4 text-center text-xs text-muted">
          Free, no spam, your picks stay yours.
        </p>
        </>
        )}
      </div>
    </div>
  );
}
