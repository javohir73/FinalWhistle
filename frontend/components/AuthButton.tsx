"use client";

import { useAuth } from "@/components/AuthProvider";

/** Sign-in / account control for the nav. Signed out → opens the auth modal;
 *  signed in → shows the display name (or email) and a sign-out button. */
export function AuthButton() {
  const { user, loading, openSignIn, logout } = useAuth();

  if (loading) return null;

  if (!user) {
    return (
      <button
        type="button"
        onClick={() => openSignIn()}
        className="rounded-lg bg-win/15 px-3 py-1.5 text-sm font-semibold text-win ring-1 ring-win/30 transition hover:bg-win/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
      >
        Sign in
      </button>
    );
  }

  const label = user.display_name || user.email.split("@")[0];
  return (
    <div className="flex items-center gap-2">
      <span className="hidden max-w-[10rem] truncate text-sm text-muted sm:inline" title={user.email}>
        {label}
      </span>
      <button
        type="button"
        onClick={() => void logout()}
        className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
      >
        Sign out
      </button>
    </div>
  );
}
