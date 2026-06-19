"use client";

import { getGroups, getKnockoutOdds } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct } from "@/lib/format";
import { Flag } from "@/components/Flag";
import { Reveal } from "@/components/Reveal";
import { ErrorState } from "@/components/States";
import { trackEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import type { Group, TournamentOdds } from "@/lib/types";
import Link from "next/link";

export function BracketsClient({
  initialOdds,
  initialGroups,
}: {
  initialOdds?: TournamentOdds[];
  initialGroups?: Group[];
}) {
  // getGroups is still fetched so the simulation pipeline stays warm and the
  // route's data contract is unchanged, even though the AI-bracket view now
  // reads only the knockout odds.
  const oddsState = useFetch(getKnockoutOdds, [], undefined, initialOdds);
  useFetch(getGroups, [], undefined, initialGroups);

  return (
    <div className="space-y-8">
      <header className="fade-up">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          The AI&apos;s <span className="text-lime-deep">bracket</span>
        </h1>

        {/* My picks / AI bracket — prototype ".seg" segmented control */}
        <div
          role="tablist"
          aria-label="Bracket views"
          className="mt-5 flex max-w-md gap-1 rounded-[14px] bg-surface-2 p-1"
        >
          <Link
            href="/my-bracket"
            role="tab"
            aria-selected={false}
            className="flex-1 rounded-[11px] px-3 py-2 text-center text-sm font-semibold text-muted transition hover:text-foreground"
          >
            My picks
          </Link>
          <span
            role="tab"
            aria-selected
            className="flex-1 rounded-[11px] bg-surface px-3 py-2 text-center text-sm font-semibold text-foreground shadow-[0_1px_3px_rgba(18,40,25,0.1)]"
          >
            AI bracket
          </span>
        </div>
      </header>

      {/* AI bracket: the model's most-likely path, round by round */}
      {oddsState.status === "error" && <ErrorState message={oddsState.message} />}
      {oddsState.status === "loading" && <SkeletonRounds />}
      {oddsState.status === "success" &&
        (oddsState.data.length === 0 ? <NotReady /> : <AIBracket odds={oddsState.data} />)}

      <p className="rounded-xl chip p-4 text-xs leading-relaxed text-muted">
        Each run simulates all 72 group matches, ranks the qualifiers, seeds the
        official Round-of-32 bracket, and plays every knockout tie (draws decided by
        a penalty model). Probabilities are the share of runs in which a team reaches
        that stage. Knockout matches are treated as neutral-venue.
      </p>
    </div>
  );
}

const ROUND_DEFS: { key: keyof TournamentOdds; label: string; take: number; final?: boolean }[] = [
  { key: "reach_r16", label: "Round of 16", take: 16 },
  { key: "reach_qf", label: "Quarter-finals", take: 8 },
  { key: "reach_sf", label: "Semi-finals", take: 4 },
  { key: "win_title", label: "Final", take: 2, final: true },
];

/** The model's most-likely path: for each round, the teams most likely to reach
 *  it, ending in a bg-pitch Final card and the predicted champion line. */
function AIBracket({ odds }: { odds: TournamentOdds[] }) {
  const champion = [...odds].sort((a, b) => (b.win_title ?? 0) - (a.win_title ?? 0))[0];

  const teamsFor = (key: keyof TournamentOdds, take: number) =>
    [...odds]
      .sort((a, b) => ((b[key] as number) ?? 0) - ((a[key] as number) ?? 0))
      .slice(0, take);

  return (
    <section>
      <p className="mb-4 text-sm leading-relaxed text-muted">
        The model&apos;s most-likely path, from thousands of simulations.
      </p>

      <div className="space-y-5">
        {ROUND_DEFS.map((round) => (
          <div key={round.label}>
            <h2 className="mb-2 font-display text-[11px] font-bold uppercase tracking-wider text-muted">
              {round.label}
            </h2>
            <div className={cn("grid gap-2", round.final ? "grid-cols-1" : "sm:grid-cols-2")}>
              {teamsFor(round.key, round.take).map((t, i) => (
                <Reveal key={t.team_id} delay={Math.min(i * 40, 240)}>
                  <Link
                    href={`/team/${t.team_id}`}
                    onClick={() => trackEvent("bracket_team_click", { team: t.team, from: round.label })}
                    className={cn(
                      "flex items-center gap-2.5 rounded-xl px-3 py-2.5 transition",
                      round.final
                        ? "panel-pitch hover:brightness-105"
                        : "glass card-hover",
                    )}
                  >
                    <Flag team={t.team} size={22} />
                    <span
                      className={cn(
                        "min-w-0 flex-1 truncate font-display text-sm font-bold tracking-tight",
                        round.final ? "text-white" : "",
                      )}
                    >
                      {t.team}
                    </span>
                    {round.final && (
                      <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0 text-win" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                        <path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0V4Z" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M17 5h2.5a1.5 1.5 0 0 1 0 5H17M7 5H4.5a1.5 1.5 0 0 0 0 5H7" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </Link>
                </Reveal>
              ))}
            </div>
          </div>
        ))}
      </div>

      {champion && (
        <p className="mt-4 px-0.5 text-[11px] leading-relaxed text-muted">
          Predicted champion:{" "}
          <Link href={`/team/${champion.team_id}`} className="font-bold text-lime-deep">
            {champion.team}
          </Link>{" "}
          · {pct(champion.win_title)} title probability.
        </p>
      )}
    </section>
  );
}

function NotReady() {
  return (
    <p className="rounded-xl chip p-4 text-sm text-muted">
      Tournament simulation hasn&apos;t run yet — check back shortly.
    </p>
  );
}

function SkeletonRounds() {
  return (
    <div className="space-y-5">
      {[16, 8, 4, 2].map((count, r) => (
        <div key={r}>
          <div className="skeleton mb-2 h-3 w-24 rounded" />
          <div className="grid gap-2 sm:grid-cols-2">
            {Array.from({ length: Math.min(count, 4) }).map((_, i) => (
              <div key={i} className="glass rounded-xl p-4">
                <div className="skeleton h-5 w-full rounded" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
