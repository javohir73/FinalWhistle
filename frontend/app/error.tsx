"use client";

import { useEffect } from "react";
import Link from "next/link";

/**
 * Route-level error boundary. If a render throws (e.g. a bad value reaching a
 * formatter), the user gets a recoverable fallback instead of a blank page.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface for logging/Sentry; never swallow silently.
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-loss/10 text-loss ring-1 ring-loss/30">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" strokeLinejoin="round" />
        </svg>
      </span>
      <h1 className="font-display text-2xl font-extrabold tracking-tight">Something went wrong</h1>
      <p className="text-sm text-muted">
        That view hit an unexpected error. You can try again, or head back to the home page.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="rounded-xl bg-win px-4 py-2 text-sm font-display font-bold text-pitch transition hover:brightness-105"
        >
          Try again
        </button>
        <Link
          href="/"
          className="rounded-xl border border-border bg-surface px-4 py-2 text-sm font-medium text-muted transition hover:border-win/40 hover:text-foreground"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}
