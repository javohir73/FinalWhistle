"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Flag } from "@/components/Flag";
import { rankTeams } from "@/lib/teamSearch";
import type { Team } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_RESULTS = 8;
const LIST_ID = "team-search-results";
const optId = (id: number) => `team-search-opt-${id}`;

/** Home-dashboard search: type a nation, pick a result, land on its
 *  /team/[id] profile. A keyboard-accessible combobox over the already-loaded
 *  teams list — display-only, no extra fetch. */
export function TeamSearch({ teams }: { teams: Team[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);

  const results = useMemo(
    () => rankTeams(teams, query).slice(0, MAX_RESULTS),
    [teams, query],
  );
  const trimmed = query.trim();
  const showList = open && trimmed.length > 0;

  const go = (team: Team) => {
    setOpen(false);
    router.push(`/team/${team.id}`);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setOpen(false);
      setHighlight(-1);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, results.length - 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
      return;
    }
    if (e.key === "Enter" && highlight >= 0 && results[highlight]) {
      e.preventDefault();
      go(results[highlight]);
    }
  };

  return (
    <div className="relative">
      <svg
        className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      >
        <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
      </svg>
      <input
        type="search"
        role="combobox"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlight(-1);
        }}
        onKeyDown={onKeyDown}
        onFocus={() => setOpen(true)}
        placeholder="Search any team…"
        aria-label="Search any team"
        aria-autocomplete="list"
        aria-expanded={showList}
        aria-controls={LIST_ID}
        aria-activedescendant={
          highlight >= 0 && results[highlight] ? optId(results[highlight].id) : undefined
        }
        autoComplete="off"
        className="w-full rounded-xl border border-border bg-surface py-3 pl-10 pr-3 text-base transition placeholder:text-muted/60 focus:border-lime-deep/40"
      />

      {showList && (
        <ul
          id={LIST_ID}
          role="listbox"
          aria-label="Team results"
          className="absolute z-20 mt-2 max-h-72 w-full overflow-y-auto rounded-xl border border-border bg-surface p-1.5 shadow-lg"
        >
          {results.map((t, i) => (
            <li key={t.id}>
              <button
                type="button"
                role="option"
                id={optId(t.id)}
                aria-selected={i === highlight}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => go(t)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm transition",
                  i === highlight ? "bg-surface-2 text-foreground" : "text-foreground hover:bg-surface-2",
                )}
              >
                <Flag team={t.name} size={24} />
                <span className="min-w-0 flex-1 truncate font-medium">{t.name}</span>
                {t.is_host && (
                  <span className="shrink-0 rounded-md bg-gold/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-gold">
                    Host
                  </span>
                )}
              </button>
            </li>
          ))}
          {results.length === 0 && (
            <li className="px-3 py-4 text-center text-sm text-muted">
              No team matches “{trimmed}”.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
