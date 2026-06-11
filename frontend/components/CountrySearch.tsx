"use client";

import { useMemo, useRef, useState } from "react";
import { Flag } from "@/components/Flag";
import type { Team } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Searchable grid of all nations. Results are ranked: prefix matches first,
 *  then substring, then alphabetical — so typing "ar" surfaces Argentina early. */
export function CountrySearch({
  teams,
  selectedId,
  onSelect,
}: {
  teams: Team[];
  selectedId?: number | null;
  onSelect: (team: Team) => void;
}) {
  const [query, setQuery] = useState("");
  const listRef = useRef<HTMLUListElement>(null);

  // The grid advertises listbox semantics, so arrow keys must move between
  // options (screen-reader users expect it; Tab alone would overpromise).
  const onListKeyDown = (e: React.KeyboardEvent) => {
    const handled = ["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"];
    if (!handled.includes(e.key)) return;
    const options = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>('button[role="option"]') ?? [],
    );
    if (options.length === 0) return;
    const current = options.indexOf(document.activeElement as HTMLButtonElement);
    let next: number;
    if (e.key === "Home") next = 0;
    else if (e.key === "End") next = options.length - 1;
    else if (e.key === "ArrowDown" || e.key === "ArrowRight")
      next = current < 0 ? 0 : Math.min(current + 1, options.length - 1);
    else next = Math.max(current - 1, 0);
    options[next]?.focus();
    e.preventDefault();
  };

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const sorted = [...teams].sort((a, b) => a.name.localeCompare(b.name));
    if (!q) return sorted;
    return sorted
      .filter((t) => t.name.toLowerCase().includes(q))
      .sort((a, b) => {
        const ap = a.name.toLowerCase().startsWith(q) ? 0 : 1;
        const bp = b.name.toLowerCase().startsWith(q) ? 0 : 1;
        return ap - bp || a.name.localeCompare(b.name);
      });
  }, [teams, query]);

  return (
    <div>
      <div className="relative">
        <svg
          className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        >
          <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search 48 nations…"
          aria-label="Search for a country"
          autoComplete="off"
          className="w-full rounded-xl border border-border bg-surface/60 py-3 pl-10 pr-3 text-base outline-none transition placeholder:text-muted/60 focus:border-win/50 focus:ring-2 focus:ring-win/20"
        />
      </div>

      <ul
        ref={listRef}
        onKeyDown={onListKeyDown}
        className="mt-4 grid max-h-[44vh] grid-cols-2 gap-2 overflow-y-auto pr-1 sm:grid-cols-3"
        role="listbox"
        aria-label="Countries"
      >
        {results.map((t) => {
          const active = t.id === selectedId;
          return (
            <li key={t.id}>
              <button
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => onSelect(t)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left text-sm transition",
                  active
                    ? "border-win/50 bg-win/10 text-foreground"
                    : "border-border bg-surface/50 text-foreground hover:border-win/40 hover:bg-surface-2/60",
                )}
              >
                <Flag team={t.name} size={26} />
                <span className="min-w-0 flex-1 truncate font-medium">{t.name}</span>
                {t.is_host && (
                  <span className="shrink-0 rounded-md bg-gold/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-gold">
                    Host
                  </span>
                )}
              </button>
            </li>
          );
        })}
        {results.length === 0 && (
          <li className="col-span-full py-6 text-center text-sm text-muted">
            No country matches “{query.trim()}”.
          </li>
        )}
      </ul>
    </div>
  );
}
