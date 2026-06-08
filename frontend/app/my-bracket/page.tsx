"use client";

import Link from "next/link";
import { getGroups, getUpcomingMatches } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useMyBracket } from "@/lib/useMyBracket";
import { Loading, ErrorState } from "@/components/States";
import { Flag } from "@/components/Flag";
import { ROUNDS } from "@/lib/bracketStructure";
import { trackEvent } from "@/lib/analytics";
import type { BFixture, Outcome, TableRow } from "@/lib/myBracket";
import { cn } from "@/lib/utils";

export default function MyBracketPage() {
  const groupsState = useFetch(getGroups, []);
  const matchesState = useFetch(getUpcomingMatches, []);

  const groups = groupsState.status === "success" ? groupsState.data : null;
  const matches = matchesState.status === "success" ? matchesState.data : null;
  const b = useMyBracket(groups, matches);

  const loading = groupsState.status === "loading" || matchesState.status === "loading";
  const error =
    groupsState.status === "error" ? groupsState.message :
    matchesState.status === "error" ? matchesState.message : null;

  return (
    <div className="space-y-8">
      <header className="fade-up">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          Build your bracket
        </h1>
        <p className="mt-2 max-w-xl text-muted">
          Pick every group game, watch the tables update, then play out the knockouts to
          your champion. Saved on this device — come back any time.
        </p>
      </header>

      {error && <ErrorState message={error} />}
      {loading && <Loading label="Loading fixtures…" />}

      {!loading && !error && b.model.length > 0 && (
        <>
          {/* Progress + reset */}
          <div className="glass flex flex-wrap items-center justify-between gap-3 rounded-2xl p-4">
            <div className="text-sm">
              <span className="font-display font-bold">
                {b.progress.groupsPicked}/{b.progress.totalGroupFixtures}
              </span>{" "}
              <span className="text-muted">group games picked</span>
              {b.champion && (
                <span className="ml-2 text-muted">· champion: <span className="font-semibold text-gold">{b.champion}</span></span>
              )}
            </div>
            <button
              type="button"
              onClick={() => { b.reset(); trackEvent("my_bracket_reset"); }}
              className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted transition hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
            >
              Reset
            </button>
          </div>

          {/* Group stage */}
          <section>
            <h2 className="mb-4 font-display text-xs font-bold uppercase tracking-[0.2em] text-muted">
              Group stage
            </h2>
            <div className="grid gap-5 lg:grid-cols-2">
              {b.model.map((g) => (
                <div key={g.letter} className="glass rounded-2xl p-4 sm:p-5">
                  <div className="mb-3 font-display text-lg font-bold tracking-tight">Group {g.letter}</div>
                  <div className="space-y-2">
                    {g.fixtures.map((fx) => (
                      <FixtureRow
                        key={fx.matchId}
                        fixture={fx}
                        pick={b.groupPicks[fx.matchId]}
                        onPick={(o) => b.setGroupPick(fx.matchId, o)}
                      />
                    ))}
                  </div>
                  <MiniTable rows={b.tables[g.letter] ?? []} teamId={b.teamId} />
                </div>
              ))}
            </div>
          </section>

          {/* Knockouts */}
          <section>
            <h2 className="mb-1 font-display text-xs font-bold uppercase tracking-[0.2em] text-muted">
              Knockouts
            </h2>
            {!b.complete ? (
              <p className="glass rounded-2xl p-5 text-sm text-muted">
                Pick all {b.progress.totalGroupFixtures} group games to unlock the knockout
                bracket. The top two of each group plus the eight best third-placed teams
                advance — seeded into the official Round of 32.
              </p>
            ) : (
              <>
                {b.champion && (
                  <div className="glass mb-5 rounded-2xl border-gold/30 bg-gold/[0.06] p-5 text-center">
                    <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-gold">Your champion</div>
                    <div className="mt-2 flex items-center justify-center gap-3">
                      <Flag team={b.champion} size={40} />
                      <span className="font-display text-2xl font-extrabold tracking-tight">{b.champion}</span>
                    </div>
                  </div>
                )}
                <div className="space-y-6">
                  {ROUNDS.map((round) => (
                    <div key={round.key}>
                      <h3 className="mb-3 font-display text-sm font-bold">{round.label}</h3>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {round.matches.map((no) => {
                          const sides = b.sidesFor(no);
                          return (
                            <TieCard
                              key={no}
                              a={sides.a}
                              b={sides.b}
                              picked={b.koPicks[no]}
                              isFinal={round.key === "final"}
                              teamId={b.teamId}
                              onPick={(team) => {
                                b.setKoPick(no, team);
                                if (round.key === "final") trackEvent("my_bracket_champion", { team });
                              }}
                            />
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>

          <p className="rounded-xl chip p-4 text-xs leading-relaxed text-muted">
            Group tables rank by points; ties are broken by the model&apos;s rating. Best
            third-placed teams are seeded into the official Round of 32. Your picks are
            stored only in this browser.{" "}
            <Link href="/brackets" className="text-win underline underline-offset-2">
              See the model&apos;s projected bracket →
            </Link>
          </p>
        </>
      )}
    </div>
  );
}

function PickButton({
  label, teamName, active, onClick, align = "left",
}: { label: string; teamName?: string; active: boolean; onClick: () => void; align?: "left" | "center" | "right" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex min-w-0 items-center gap-1.5 rounded-lg border px-2 py-1.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50",
        align === "right" && "flex-row-reverse text-right",
        align === "center" && "justify-center",
        active ? "border-win/50 bg-win/10 text-foreground" : "border-border text-muted hover:text-foreground",
      )}
    >
      {teamName && <Flag team={teamName} size={16} />}
      <span className="truncate">{label}</span>
    </button>
  );
}

function FixtureRow({
  fixture, pick, onPick,
}: { fixture: BFixture; pick?: Outcome; onPick: (o: Outcome) => void }) {
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1.5">
      <PickButton label={fixture.home} teamName={fixture.home} active={pick === "home"} onClick={() => onPick("home")} />
      <PickButton label="Draw" active={pick === "draw"} onClick={() => onPick("draw")} align="center" />
      <PickButton label={fixture.away} teamName={fixture.away} active={pick === "away"} onClick={() => onPick("away")} align="right" />
    </div>
  );
}

function MiniTable({ rows, teamId }: { rows: TableRow[]; teamId: Record<string, number> }) {
  if (rows.length === 0) return null;
  return (
    <table className="mt-4 w-full text-sm">
      <thead className="sr-only">
        <tr>
          <th scope="col">Position</th>
          <th scope="col">Team</th>
          <th scope="col">Points</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.name} className={cn("border-t border-border/50", i < 2 && "bg-win/[0.05]")}>
            <td className="w-5 py-1.5 text-center text-xs font-semibold text-muted">{i + 1}</td>
            <td className="py-1.5">
              <Link
                href={teamId[r.name] ? `/team/${teamId[r.name]}` : "#"}
                className="flex items-center gap-2 hover:text-win"
              >
                <Flag team={r.name} size={18} />
                <span className="min-w-0 truncate font-medium">{r.name}</span>
                {i === 2 && <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted">3rd</span>}
              </Link>
            </td>
            <td className="py-1.5 text-right tabular-nums font-semibold">{r.points}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TieCard({
  a, b, picked, isFinal, teamId, onPick,
}: {
  a?: string; b?: string; picked?: string; isFinal?: boolean;
  teamId: Record<string, number>; onPick: (team: string) => void;
}) {
  return (
    <div className={cn("glass rounded-xl p-2", isFinal && "border-gold/30")}>
      {[a, b].map((team, i) => (
        <button
          key={i}
          type="button"
          disabled={!team}
          onClick={() => team && onPick(team)}
          aria-pressed={!!team && picked === team}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50",
            !team && "cursor-not-allowed text-muted/50",
            team && picked === team ? "bg-win/15 font-semibold text-foreground" : team ? "text-foreground/90 hover:bg-surface-2/60" : "",
          )}
        >
          {team ? <Flag team={team} size={20} /> : <span className="h-5 w-5 rounded-full bg-surface-2" />}
          <span className="min-w-0 flex-1 truncate">{team ?? "To be decided"}</span>
          {team && picked === team && <span className="shrink-0 text-win" aria-hidden>✓</span>}
        </button>
      ))}
    </div>
  );
}
