"use client";

import { useEffect, useRef, useState } from "react";
import type { SessionUser } from "@/lib/session";

function initials(user: SessionUser): string {
  const name = (user.display_name || "").trim();
  if (name) {
    const parts = name.split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return (user.email[0] || "?").toUpperCase();
}

/** Signed-in indicator: a circular avatar with the user's initials (top-right),
 *  opening a small menu with their email + Sign out. */
export function AccountMenu({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const label = user.display_name || user.email;

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account: ${label}`}
        title={label}
        className="grid h-9 w-9 place-items-center rounded-full bg-win/15 text-sm font-bold text-win ring-1 ring-win/30 transition hover:bg-win/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/60"
      >
        {initials(user)}
      </button>

      {open && (
        <div
          role="menu"
          className="glass absolute right-0 z-50 mt-2 w-56 rounded-xl border border-border/70 p-1.5 shadow-xl"
        >
          <div className="px-3 py-2">
            <div className="truncate text-sm font-semibold">{user.display_name || "Signed in"}</div>
            <div className="truncate text-xs text-muted">{user.email}</div>
          </div>
          <div className="my-1 border-t border-border/60" />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="w-full rounded-lg px-3 py-2 text-left text-sm font-medium text-muted transition hover:bg-surface-2/60 hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
