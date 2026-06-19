"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Flag } from "@/components/Flag";
import { CountrySearch } from "@/components/CountrySearch";
import type { SelectedCountry } from "@/lib/useSelectedCountry";
import type { Team } from "@/lib/types";

/** Quick-pick chips: the three hosts, then the strongest sides by Elo. */
function suggestions(teams: Team[]): Team[] {
  const hosts = teams.filter((t) => t.is_host);
  const hostIds = new Set(hosts.map((t) => t.id));
  const top = [...teams]
    .filter((t) => !hostIds.has(t.id))
    .sort((a, b) => (b.elo_rating ?? 0) - (a.elo_rating ?? 0))
    .slice(0, 6);
  return [...hosts, ...top];
}

/**
 * Country-first entry point. With no selection it shows the chooser; once a
 * country is picked it shows a focused preview with the "Predict my team" CTA
 * that kicks off the AI-forecast reveal. Fully anonymous.
 */
export function CountryOnboarding({
  teams,
  selection,
  onSelect,
  onPredict,
  onChangeCountry,
}: {
  teams: Team[];
  selection: SelectedCountry | null;
  onSelect: (team: Team) => void;
  onPredict: () => void;
  onChangeCountry: () => void;
}) {
  const selectedTeam = useMemo(
    () => (selection ? teams.find((t) => t.id === selection.team_id) ?? null : null),
    [teams, selection],
  );
  const picks = useMemo(() => suggestions(teams), [teams]);

  // ---- Selected: focused preview + Predict CTA ----
  if (selection) {
    const name = selectedTeam?.name ?? selection.team;
    return (
      <section className="mx-auto max-w-xl py-16 text-center sm:py-24">
        <p className="font-display text-sm font-bold uppercase tracking-[0.2em] text-lime-deep">
          Your team
        </p>
        <div className="mt-6 flex flex-col items-center gap-4">
          <span className="grid place-items-center rounded-2xl bg-win/10 p-3.5">
            <Flag team={name} size={88} />
          </span>
          <h1 className="font-display text-4xl font-extrabold tracking-tight sm:text-5xl">
            {name}
          </h1>
          {selectedTeam && (
            <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 text-sm text-muted">
              {selectedTeam.fifa_rank != null && (
                <span>FIFA rank <span className="font-semibold text-foreground">#{selectedTeam.fifa_rank}</span></span>
              )}
              {selectedTeam.elo_rating != null && (
                <span>Elo <span className="font-semibold text-foreground">{Math.round(selectedTeam.elo_rating)}</span></span>
              )}
              {selectedTeam.confederation && <span>{selectedTeam.confederation}</span>}
            </div>
          )}
        </div>

        <p className="mx-auto mt-6 max-w-sm text-muted">
          Build {name}&rsquo;s World Cup outlook — matches, odds, strengths, and where
          your calls differ from the AI.
        </p>

        <div className="mt-8 flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={onPredict}
            className="group inline-flex items-center gap-2 rounded-xl bg-win px-7 py-3.5 font-display text-lg font-bold text-pitch transition hover:brightness-105"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M5 3l14 9-14 9V3z" strokeLinejoin="round" />
            </svg>
            Predict my team
          </button>
          <button
            type="button"
            onClick={onChangeCountry}
            className="text-sm font-medium text-muted underline-offset-2 transition hover:text-foreground hover:underline"
          >
            Choose a different country
          </button>
        </div>
      </section>
    );
  }

  // ---- No selection: the chooser ----
  return (
    <section className="mx-auto max-w-2xl py-12 sm:py-16">
      <div className="text-center">
        <div className="mb-5 inline-flex items-center gap-2 rounded-full chip px-3 py-1 text-xs font-medium text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-win" />
          FIFA World Cup 2026 · USA · Canada · Mexico
        </div>
        <h1 className="font-display text-4xl font-extrabold leading-[1.05] tracking-tight text-foreground sm:text-6xl">
          Choose your <span className="text-lime-deep">World Cup team</span>
        </h1>
        <p className="mx-auto mt-4 max-w-md text-lg text-muted">
          Follow their matches, make your predictions, and compare your picks with the AI.
        </p>
      </div>

      <div className="glass mt-9 rounded-2xl p-4 sm:p-5">
        <CountrySearch teams={teams} onSelect={onSelect} />
      </div>

      {picks.length > 0 && (
        <div className="mt-6">
          <p className="mb-2.5 text-center text-xs font-semibold uppercase tracking-wider text-muted">
            Popular picks
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {picks.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => onSelect(t)}
                className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-sm font-medium transition hover:bg-surface-2"
              >
                <Flag team={t.name} size={20} />
                {t.name}
                {t.is_host && (
                  <span className="rounded bg-gold/15 px-1 text-[9px] font-bold uppercase tracking-wide text-gold">Host</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      <p className="mt-9 text-center text-sm text-muted">
        Just browsing?{" "}
        <Link href="/matches" className="font-medium text-lime-deep underline-offset-2 hover:underline">
          Explore all matches
        </Link>
        {" · "}
        <Link href="/brackets" className="font-medium text-lime-deep underline-offset-2 hover:underline">
          Road to the final
        </Link>
      </p>
    </section>
  );
}
