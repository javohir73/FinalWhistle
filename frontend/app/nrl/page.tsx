import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlLadderServer, getNrlMatchesServer, getOriginSeriesServer } from "@/lib/api";
import { StandingsTable } from "@/components/StandingsTable";
import { IntelPanel } from "@/components/IntelPanel";
import { FeatureHero } from "@/components/FeatureHero";
import { TimelineSpine } from "@/components/TimelineSpine";
import { ladderRowsToStandings, nrlExpectedMargin, nrlMatchHref, nrlMatchToSummary } from "@/lib/nrlAdapters";
import { COMPETITIONS } from "@/lib/sports";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "NRL predictions — FinalWhistle",
  description: "Match predictions from the FinalWhistle ML model, ladder and model record for the NRL season.",
};

/** NRL home: current-round fixtures + mini ladder + movers. The "current"
 *  round is the first round containing a scheduled match (else the last). */
export default async function NrlHomePage() {
  const [fixtures, ladder, origin] = await Promise.all([
    getNrlMatchesServer().catch(() => null),
    getNrlLadderServer().catch(() => null),
    getOriginSeriesServer().catch(() => null),
  ]);
  if (!fixtures) notFound();

  const current =
    fixtures.rounds.find((r) => r.matches.some((m) => m.status === "scheduled")) ??
    fixtures.rounds[fixtures.rounds.length - 1];

  // The feature: the round's first still-to-play match (else its first match).
  // It leads as the FeatureHero, so the timeline below excludes it — no dupes.
  const featured =
    current?.matches.find((m) => m.status === "scheduled") ?? current?.matches[0] ?? null;
  const roundMatches = (current?.matches ?? []).filter((m) => m.id !== featured?.id);

  // Per-card maps keyed by match_id (= NrlMatch.id) — the detail href and the
  // model's expected margin, threaded onto each compact card in the spine.
  const cardHref: Record<number, string | null> = {};
  const cardMargin: Record<number, number | null> = {};
  for (const m of roundMatches) {
    cardHref[m.id] = nrlMatchHref(fixtures.season, current?.round, m.match_no);
    cardMargin[m.id] = nrlExpectedMargin(m);
  }

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL · Season {fixtures.season}</h1>
      <p className="mt-1 text-sm text-muted">
        Round {current?.round ?? "—"} · model predictions frozen at kickoff
      </p>

      <div className="mt-6">
        <FeatureHero
          match={featured ? nrlMatchToSummary(featured) : null}
          comp="nrl"
          tz="Australia/Sydney"
          badge="club"
          href={
            featured
              ? nrlMatchHref(fixtures.season, current?.round, featured.match_no) ?? undefined
              : undefined
          }
          margin={featured ? nrlExpectedMargin(featured) : null}
        />
      </div>

      <IntelPanel sport="nrl" />

      {origin ? (
        <Link
          href="/nrl/origin"
          className="glass mt-6 block rounded-2xl p-4 transition hover:bg-white/5"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
                State of Origin · {origin.season}
              </p>
              <p className="mt-1 font-display text-lg font-extrabold">
                NSW Blues {origin.series.blues_wins} – {origin.series.maroons_wins} QLD
                Maroons
                {origin.series.drawn_games ? ` · ${origin.series.drawn_games} drawn` : ""}
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-lime-deep">
              Series &amp; model →
            </span>
          </div>
        </Link>
      ) : null}

      <div className="mt-6 grid gap-4 md:grid-cols-[1fr_320px]">
        {roundMatches.length > 0 ? (
          <TimelineSpine
            days={[
              {
                key: `round-${current?.round ?? "tbc"}`,
                heading: `Round ${current?.round ?? "TBC"}`,
                matches: roundMatches.map(nrlMatchToSummary),
              },
            ]}
            tz="Australia/Sydney"
            badge="club"
            cardHref={cardHref}
            cardMargin={cardMargin}
          />
        ) : (
          <p className="text-sm text-muted">No other fixtures this round.</p>
        )}
        {ladder ? (
          <div className="glass h-fit rounded-2xl p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
                Ladder
              </span>
              <Link href="/nrl/ladder" className="text-xs font-semibold text-lime-deep">
                Full ladder →
              </Link>
            </div>
            <StandingsTable
              standings={ladderRowsToStandings(ladder.rows).slice(0, 4)}
              zones={COMPETITIONS.nrl.zones}
              badge="club"
              teamBasePath="/nrl/team"
              teamHeader="Club"
              columns={["pts"]}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
