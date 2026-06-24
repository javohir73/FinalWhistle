"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { verifyEmail, friendlyAuthError } from "@/lib/session";
import { useAuth } from "@/components/AuthProvider";

type State = "verifying" | "done" | "error" | "notoken";

/** Consumes the ?token= from a verification email (via POST, so a link-preview
 *  GET can't burn it), then clears the in-app banner by refreshing /me. */
export function VerifyEmailClient() {
  const token = useSearchParams().get("token");
  const { refresh } = useAuth();
  const [state, setState] = useState<State>(token ? "verifying" : "notoken");
  const [msg, setMsg] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true;
    verifyEmail(token)
      .then(() => {
        setState("done");
        void refresh(); // clears the verify banner in this session
      })
      .catch((e) => {
        setState("error");
        setMsg(friendlyAuthError(e));
      });
  }, [token, refresh]);

  return (
    <div className="mx-auto max-w-sm px-4 py-16">
      <div className="glass rounded-2xl p-6 text-center">
        {state === "verifying" && (
          <p className="text-sm text-muted">Verifying your email…</p>
        )}
        {state === "done" && (
          <>
            <h1 className="mb-2 font-display text-xl font-extrabold tracking-tight">
              Email verified ✓
            </h1>
            <p className="mb-4 text-sm text-muted">You&rsquo;re all set.</p>
            <Home />
          </>
        )}
        {state === "notoken" && (
          <>
            <h1 className="mb-2 font-display text-xl font-extrabold tracking-tight">
              Verification link invalid
            </h1>
            <p className="mb-4 text-sm text-muted">
              This link is missing its token. Open the most recent email, or resend
              from the banner once you&rsquo;re signed in.
            </p>
            <Home />
          </>
        )}
        {state === "error" && (
          <>
            <h1 className="mb-2 font-display text-xl font-extrabold tracking-tight">
              Couldn&rsquo;t verify
            </h1>
            <p className="mb-4 text-sm text-loss">{msg}</p>
            <p className="mb-4 text-sm text-muted">
              The link may have expired. Sign in and resend a fresh one.
            </p>
            <Home />
          </>
        )}
      </div>
    </div>
  );
}

function Home() {
  return (
    <Link
      href="/"
      className="block text-center text-sm font-semibold text-lime-deep underline-offset-2 hover:underline"
    >
      Back to FinalWhistle
    </Link>
  );
}
