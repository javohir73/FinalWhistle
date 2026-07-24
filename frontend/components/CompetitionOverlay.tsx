"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  COMPETITIONS,
  competitionFromPathname,
  competitionsForSport,
  type Competition,
  type CompetitionId,
  type SportId,
} from "@/lib/sports";
import {
  clearPinnedCompetition,
  readPinnedCompetition,
  writePinnedCompetition,
} from "@/lib/competitionPrefs";
import { cn } from "@/lib/utils";

/** Displayed in this order regardless of COMPETITIONS' insertion order --
 *  football first (it's most of the product today), NRL after. */
const SPORT_SECTIONS: Array<{ sport: SportId; heading: string }> = [
  { sport: "football", heading: "Football" },
  { sport: "nrl", heading: "NRL" },
];

/** Pinned competition sorts first within its own sport section; everything
 *  else keeps COMPETITIONS' stable insertion order. */
function orderedForSection(sport: SportId, pinned: CompetitionId | null): Competition[] {
  const list = competitionsForSport(sport);
  const pinnedIdx = pinned ? list.findIndex((c) => c.id === pinned) : -1;
  if (pinnedIdx <= 0) return list;
  const reordered = list.slice();
  const [pin] = reordered.splice(pinnedIdx, 1);
  reordered.unshift(pin);
  return reordered;
}

function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
    </svg>
  );
}

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.8}
      aria-hidden="true"
    >
      <path d="M12 3.5l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17.4l-5.4 2.9 1-6.1L3.2 10l6.1-.9L12 3.5Z" strokeLinejoin="round" />
    </svg>
  );
}

/** Header trigger + full-screen typographic competition switcher (Floodlight
 *  P1 slice p1-s5). Replaces SportSwitcher: one sport toggle grows into one
 *  overlay listing every competition, section-separated by sport, with a
 *  starrable pin that persists in localStorage (lib/competitionPrefs.ts).
 *  P1 keeps this minimal and token-based -- it's the one new surface this
 *  phase ships; no other screen gets a visual pass. */
export function CompetitionOverlay() {
  const pathname = usePathname();
  const active = competitionFromPathname(pathname);
  const [open, setOpen] = useState(false);
  // Starts null on the server render and every first client render so SSR
  // and the initial hydration pass agree -- the real value only exists in
  // localStorage, read after mount.
  const [pinned, setPinned] = useState<CompetitionId | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setPinned(readPinnedCompetition());
  }, []);

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  // Escape closes -- P1's "focus-trapped enough" bar; a full Tab-cycle trap
  // isn't required for this slice.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const togglePin = (id: CompetitionId) => {
    if (pinned === id) {
      clearPinnedCompetition();
      setPinned(null);
    } else {
      writePinnedCompetition(id);
      setPinned(id);
    }
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="ml-4 inline-flex items-center gap-1 rounded-full bg-surface-2 px-3 py-1.5 text-[13px] font-semibold text-foreground transition hover:bg-surface"
      >
        {COMPETITIONS[active].shortLabel}
        <ChevronIcon />
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Choose a competition"
          className="fixed inset-0 z-[60] overflow-y-auto bg-background/95 backdrop-blur-xl"
          onClick={close}
        >
          <div className="mx-auto max-w-3xl px-6 py-16 sm:py-24" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              onClick={close}
              aria-label="Close"
              className="fixed right-5 top-5 grid h-10 w-10 place-items-center rounded-full text-muted transition hover:bg-surface-2 hover:text-foreground"
            >
              <CloseIcon />
            </button>

            {SPORT_SECTIONS.map(({ sport, heading }) => {
              const list = orderedForSection(sport, pinned);
              if (list.length === 0) return null;
              return (
                <section key={sport} className="mb-12 last:mb-0">
                  <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                    {heading}
                  </h2>
                  <ul>
                    {list.map((c) => {
                      const isActive = c.id === active;
                      const isPinned = pinned === c.id;
                      const row = (
                        <>
                          <span
                            className={cn(
                              "font-display text-3xl font-bold tracking-tight sm:text-5xl",
                              isActive ? "text-lime-deep" : c.enabled ? "text-foreground" : "text-muted",
                            )}
                          >
                            {c.label}
                          </span>
                          <span
                            className="rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide"
                            style={{
                              backgroundColor: `hsl(var(${c.accentVar}) / 0.12)`,
                              color: `hsl(var(${c.accentVar}))`,
                            }}
                          >
                            {c.shortLabel}
                          </span>
                          {!c.enabled && (
                            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted">
                              Soon
                            </span>
                          )}
                        </>
                      );
                      return (
                        <li
                          key={c.id}
                          className="flex items-center gap-3 border-b border-border py-4 last:border-0"
                        >
                          {c.enabled ? (
                            <Link
                              href={c.basePath}
                              onClick={close}
                              aria-current={isActive ? "page" : undefined}
                              className="flex flex-1 flex-wrap items-center gap-3"
                            >
                              {row}
                            </Link>
                          ) : (
                            <div aria-disabled="true" className="flex flex-1 flex-wrap items-center gap-3">
                              {row}
                            </div>
                          )}
                          {c.enabled && (
                            <button
                              type="button"
                              onClick={() => togglePin(c.id)}
                              aria-pressed={isPinned}
                              aria-label={isPinned ? `Unpin ${c.label}` : `Pin ${c.label}`}
                              className={cn(
                                "shrink-0 rounded-full p-2 transition hover:text-foreground",
                                isPinned ? "text-lime-deep" : "text-muted",
                              )}
                            >
                              <StarIcon filled={isPinned} />
                            </button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
