"use client";

import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/clerk-react";
import { CLERK_ENABLED } from "@/lib/auth";

/** Sign-in / account control for the nav. Renders nothing (and touches no Clerk
 *  hook) unless Clerk is configured. */
export function AuthButton() {
  if (!CLERK_ENABLED) return null;
  return (
    <>
      <SignedOut>
        <SignInButton mode="modal">
          <button
            type="button"
            className="rounded-lg bg-win/15 px-3 py-1.5 text-sm font-semibold text-win ring-1 ring-win/30 transition hover:bg-win/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
          >
            Sign in
          </button>
        </SignInButton>
      </SignedOut>
      <SignedIn>
        <UserButton afterSignOutUrl="/" />
      </SignedIn>
    </>
  );
}
