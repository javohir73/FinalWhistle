import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlMatchesServer } from "@/lib/api";
import { SportMatchCard } from "@/components/SportMatchCard";
import { APP_NAME } from "@/lib/constants";

export const revalidate = 300;

function parseRound(n: string): number | null {
  return /^\d+$/.test(n) ? Number(n) : null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ n: string }>;
}): Promise<Metadata> {
  const { n } = await params;
  const round = parseRound(n);
  if (round == null) return { title: `NRL round — ${APP_NAME}` };
  return {
    title: `NRL round ${round} — ${APP_NAME}`,
    alternates: { canonical: `/nrl/round/${round}` },
  };
}

export default async function NrlRoundPage({
  params,
}: {
  params: Promise<{ n: string }>;
}) {
  const { n } = await params;
  const round = parseRound(n);
  if (round == null) notFound();

  const fixtures = await getNrlMatchesServer().catch(() => null);
  if (!fixtures) notFound();

  const roundNumbers = fixtures.rounds
    .map((r) => r.round)
    .filter((r): r is number => r != null)
    .sort((a, b) => a - b);
  const current = fixtures.rounds.find((r) => r.round === round);
  if (!current) notFound();

  const idx = roundNumbers.indexOf(round);
  const prevRound = idx > 0 ? roundNumbers[idx - 1] : null;
  const nextRound = idx >= 0 && idx < roundNumbers.length - 1 ? roundNumbers[idx + 1] : null;

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-extrabold">Round {round}</h1>
        <span className="text-sm text-muted">Season {fixtures.season}</span>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm">
        {prevRound != null ? (
          <Link href={`/nrl/round/${prevRound}`} className="font-semibold text-lime-deep">
            ← Round {prevRound}
          </Link>
        ) : (
          <span />
        )}
        {nextRound != null ? (
          <Link href={`/nrl/round/${nextRound}`} className="font-semibold text-lime-deep">
            Round {nextRound} →
          </Link>
        ) : (
          <span />
        )}
      </div>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {current.matches.map((m) => (
          <SportMatchCard
            key={m.match_no}
            match={m}
            eyebrow={`Round ${round}`}
            season={fixtures.season}
            round={round}
          />
        ))}
      </div>
    </div>
  );
}
