import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlMatchesServer, getNrlTipsheetServer } from "@/lib/api";
import { SportMatchCard } from "@/components/SportMatchCard";
import { TipsheetBlock } from "@/components/nrl/TipsheetBlock";
import { APP_NAME } from "@/lib/constants";

export const revalidate = 300;

function parseRound(n: string): number | null {
  return /^\d+$/.test(n) ? Number(n) : null;
}

/** Pre-render the current and next round permalinks at deploy (design doc:
 *  NRL Round Tips, Slice 1 rendering bullet) -- these are the links actually
 *  shared to a comp group chat or r/nrl, and the ones that must never block
 *  on a Render cold start. `dynamicParams` defaults to true, so any round not
 *  returned here (last week's, or the whole archive) still renders -- just
 *  on demand, behind loading.tsx, with the same ~300s ISR revalidate. The
 *  tipsheet endpoint already resolves "current" the same way nrl_tips.py's
 *  `_current_round` does, so reusing it here (rather than re-deriving from
 *  match status) keeps one source of truth for what "current" means. */
export async function generateStaticParams() {
  const [fixtures, tipsheet] = await Promise.all([
    getNrlMatchesServer().catch(() => null),
    getNrlTipsheetServer().catch(() => null),
  ]);
  if (!fixtures || !tipsheet) return [];

  const roundNumbers = fixtures.rounds
    .map((r) => r.round)
    .filter((r): r is number => r != null)
    .sort((a, b) => a - b);
  const idx = roundNumbers.indexOf(tipsheet.round);
  const rounds = idx === -1 ? [tipsheet.round] : roundNumbers.slice(idx, idx + 2);
  return rounds.map((n) => ({ n: String(n) }));
}

/** Title/description carry the tipsheet's honest-record SEO angle (design
 *  doc: NRL Round Tips, Slice 1) rather than the site's usual "X — APP_NAME"
 *  shape -- the fetch here is the same getNrlMatchesServer() call the page
 *  body makes below, which Next dedupes per request, so this costs nothing
 *  extra at request time. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ n: string }>;
}): Promise<Metadata> {
  const { n } = await params;
  const round = parseRound(n);
  if (round == null) return { title: `NRL round — ${APP_NAME}` };
  const fixtures = await getNrlMatchesServer().catch(() => null);
  const title = fixtures
    ? `NRL Round ${round} tips (${fixtures.season}) — AI predictions with a public record`
    : `NRL Round ${round} tips — AI predictions with a public record`;
  return {
    title,
    description: `The model's pick for every NRL Round ${round} fixture — win probability, expected margin, and a season record graded after full time, misses published too.`,
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

  // The tipsheet is additive -- a hiccup here must not take down the fixture
  // list above (same rationale as the match detail page's Wave 2/3 sections).
  const tipsheet = await getNrlTipsheetServer(fixtures.season, round).catch(() => null);

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
      {tipsheet ? (
        <div className="mt-6">
          <TipsheetBlock tipsheet={tipsheet} />
        </div>
      ) : (
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
      )}
    </div>
  );
}
