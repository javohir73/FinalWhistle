import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNrlMatchesServer } from "@/lib/api";
import { SportMatchCard } from "@/components/SportMatchCard";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL fixtures — FinalWhistle" };

export default async function NrlMatchesPage() {
  const fixtures = await getNrlMatchesServer().catch(() => null);
  if (!fixtures) notFound();

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL fixtures</h1>
      {fixtures.rounds.map((round) => (
        <section key={String(round.round)} className="mt-8">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
            Round {round.round ?? "TBC"}
          </h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {round.matches.map((m) => (
              <SportMatchCard
                key={m.match_no}
                match={m}
                eyebrow={`Round ${round.round ?? "TBC"}`}
                season={fixtures.season}
                round={round.round}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
