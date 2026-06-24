"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { resetPassword, friendlyAuthError } from "@/lib/session";

/** Consumes the ?token= from a reset email and sets a new password. Display-only
 *  states: missing token, the form, success, and a friendly error (e.g. an
 *  expired/used link) with a route back to request a fresh one. */
export function ResetPasswordClient() {
  const token = useSearchParams().get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const field =
    "w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground outline-none transition focus:border-win";

  if (!token) {
    return (
      <Shell title="Reset link invalid">
        <p className="text-sm text-muted">
          This reset link is missing or incomplete. Open the most recent email, or
          request a new link from the sign-in screen.
        </p>
        <Home />
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell title="Password updated">
        <p className="text-sm text-foreground">
          Your password has been updated. You can sign in with it now.
        </p>
        <Home label="Back to FinalWhistle" />
      </Shell>
    );
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError("Those passwords don’t match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell title="Choose a new password">
      <form onSubmit={submit} className="space-y-3">
        <div className="relative">
          <input
            type={show ? "text" : "password"}
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="New password (8+ characters)"
            aria-label="New password"
            className={`${field} pr-11`}
          />
          <button
            type="button"
            onClick={() => setShow((v) => !v)}
            aria-label={show ? "Hide password" : "Show password"}
            aria-pressed={show}
            className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-lg text-muted transition hover:text-foreground"
          >
            {show ? "🙈" : "👁"}
          </button>
        </div>
        <input
          type={show ? "text" : "password"}
          required
          minLength={8}
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder="Confirm new password"
          aria-label="Confirm new password"
          className={field}
        />
        {error && <p className="text-sm text-loss">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-xl bg-win px-4 py-3 text-sm font-bold text-pitch transition hover:brightness-110 disabled:opacity-50"
        >
          {busy ? "Please wait…" : "Update password"}
        </button>
      </form>
    </Shell>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-sm px-4 py-16">
      <div className="glass rounded-2xl p-6">
        <h1 className="mb-4 font-display text-xl font-extrabold tracking-tight">{title}</h1>
        <div className="space-y-4">{children}</div>
      </div>
    </div>
  );
}

function Home({ label = "Back to home" }: { label?: string }) {
  return (
    <Link
      href="/"
      className="block text-center text-sm font-semibold text-lime-deep underline-offset-2 hover:underline"
    >
      {label}
    </Link>
  );
}
