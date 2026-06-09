"use client";

import { useEffect } from "react";

/** Small transient confirmation popup (e.g. after sign-up). Auto-dismisses. */
export function AuthToast({
  message,
  onDone,
  ms = 3800,
}: {
  message: string | null;
  onDone: () => void;
  ms?: number;
}) {
  useEffect(() => {
    if (!message) return;
    const id = setTimeout(onDone, ms);
    return () => clearTimeout(id);
  }, [message, onDone, ms]);

  if (!message) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="fade-up fixed bottom-6 left-1/2 z-[120] flex -translate-x-1/2 items-center gap-2 rounded-xl border border-win/30 bg-surface/95 px-4 py-3 text-sm font-medium shadow-lg backdrop-blur"
    >
      <span className="grid h-5 w-5 place-items-center rounded-full bg-win/20 text-win" aria-hidden>
        ✓
      </span>
      {message}
    </div>
  );
}
