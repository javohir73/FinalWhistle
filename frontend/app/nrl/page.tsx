import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlLadderServer, getNrlMatchesServer } from "@/lib/api";
import { LadderTable } from "@/components/LadderTable";
import { MoversPanel } from "@/components/MoversPanel";
import { SportMatchCard } from "@/components/SportMatchCard";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "NRL predictions — FinalWhistle",
  description: "AI match predictions, ladder and model record for the NRL season.",
};

/** NRL home: current-round fixtures + mini ladder + movers. The "current"
 *  round is the first round containing a scheduled match (else the last). */
export default async function NrlHomePage() {
  const [fixtures, ladder] = await Promise.all([
    getNrlMatchesServer(),
    getNrlLadderServer(),
  ]);
  if (!fixtures) notFound();

  const current =
    fixtures.rounds.find((r) => r.matches.some((m) => m.status === "scheduled")) ??
    fixtures.rounds[fixtures.rounds.length - 1];

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL · Season {fixtures.season}</h1>
      <p className="mt-1 text-sm text-muted">
        Round {current?.round ?? "—"} · model predictions frozen at kickoff
      </p>

      <MoversPanel sport="nrl" />

      <div className="mt-6 grid gap-4 md:grid-cols-[1fr_320px]">
        <div className="grid gap-4">
          {(current?.matches ?? []).map((m) => (
            <SportMatchCard key={m.match_no} match={m} eyebrow={`Round ${current?.round}`} />
          ))}
        </div>
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
            <LadderTable rows={ladder.rows} compact />
          </div>
        ) : null}
      </div>
    </div>
  );
}
