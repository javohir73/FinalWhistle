"use client";

import { useAuth } from "@/components/AuthProvider";
import { AccountMenu } from "@/components/AccountMenu";

/** Nav auth control. Signed in → an account circle (initials) with a Sign-out
 *  menu, shown on every page. Signed out → a "Sign in" button that opens the
 *  modal. While the very first session check is still pending (and no cached
 *  user), render nothing to avoid flashing the wrong state. */
export function AuthButton() {
  const { user, loading, openSignIn, logout, deleteAccount } = useAuth();

  if (user)
    return <AccountMenu user={user} onLogout={() => void logout()} onDeleteAccount={deleteAccount} />;
  if (loading) return null;

  return (
    <button
      type="button"
      onClick={() => openSignIn()}
      className="rounded-lg bg-win/15 px-3 py-1.5 text-sm font-semibold text-lime-deep ring-1 ring-win/30 transition hover:bg-win/25"
    >
      Sign in
    </button>
  );
}
