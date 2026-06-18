"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/session";

/** Confirm dialog for permanent account deletion. Re-auth (password) is required;
 *  on success the account is anonymized server-side and the caller is signed out.
 *  Presentational — the actual deletion happens in `onConfirm`. */
export function DeleteAccountModal({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (password: string) => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firstField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setError(null);
      setPassword("");
      setTimeout(() => firstField.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onConfirm(password);
      // On success the account is gone; the parent unmounts this via auth state.
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong — please try again.");
      setBusy(false);
    }
  };

  const field =
    "w-full rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm outline-none focus:border-loss/50 focus:ring-2 focus:ring-loss/20";

  return (
    <div
      className="fixed inset-0 z-[100] grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Delete account"
      onClick={onClose}
    >
      <div className="glass w-full max-w-sm rounded-2xl p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-display text-lg font-extrabold tracking-tight text-loss">
          Delete your account
        </h2>
        <p className="mt-2 text-sm text-muted">
          This permanently removes your email, name and per-match picks, and signs you out
          everywhere. It can&apos;t be undone. If your bracket is on the public leaderboard, the
          entry stays under <span className="font-semibold text-foreground">&ldquo;Deleted user&rdquo;</span>.
          Enter your password to confirm.
        </p>

        <form onSubmit={submit} className="mt-4 space-y-3">
          <input
            ref={firstField}
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Your password"
            aria-label="Password"
            autoComplete="current-password"
            className={field}
          />
          {error && (
            <p role="alert" className="text-sm font-medium text-loss">
              {error}
            </p>
          )}
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="flex-1 rounded-lg border border-border px-3 py-2 text-sm font-semibold text-muted transition hover:bg-surface-2/60 hover:text-foreground disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || !password}
              className="flex-1 rounded-lg bg-loss/15 px-3 py-2 text-sm font-bold text-loss ring-1 ring-loss/30 transition hover:bg-loss/25 disabled:opacity-60"
            >
              {busy ? "Deleting…" : "Delete account"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
