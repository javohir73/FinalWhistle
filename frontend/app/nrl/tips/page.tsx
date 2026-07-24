import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlTipsheetServer } from "@/lib/api";
import { TipsheetBlock } from "@/components/nrl/TipsheetBlock";
import { NrlTipsPlaySection } from "@/components/nrl/NrlTipsPlaySection";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "NRL tips this week — AI predictions with a public record",
  description:
    "The model's pick for every fixture in this week's NRL round — win probability, expected margin, and a season record graded after full time, misses published too.",
  alternates: { canonical: "/nrl/tips" },
};

/** Evergreen current-round tipsheet (design doc: NRL Round Tips, Slice 1).
 *  No round param -- the endpoint resolves the current round itself, so this
 *  page's content rolls week to week under one stable URL. Permalinks for a
 *  specific round live at /nrl/round/[n], which carries the same block. */
export default async function NrlTipsPage() {
  const tipsheet = await getNrlTipsheetServer().catch(() => null);
  if (!tipsheet) notFound();

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-extrabold">NRL tips</h1>
        <span className="text-sm text-muted">Round {tipsheet.round} · {tipsheet.season}</span>
      </div>
      <div className="mt-6">
        <TipsheetBlock tipsheet={tipsheet} />
      </div>

      {/* Slice 3 teaser: same card idiom as the NRL home page's Origin
       *  entry point (glass, full-card Link, small-caps label + "→" line). */}
      <Link href="/nrl/run-home" className="glass mt-6 block rounded-2xl p-4 transition hover:bg-white/5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
              Finals race
            </p>
            <p className="mt-1 font-display text-lg font-extrabold">Predict your club&apos;s run home</p>
          </div>
          <span className="shrink-0 text-xs font-semibold text-lime-deep">Play it out →</span>
        </div>
      </Link>

      {/* Beat-the-AI loop (Slice 2): play, "you vs the AI", leaderboard --
       *  design doc scopes all of it to /nrl/tips, not the round permalinks. */}
      <NrlTipsPlaySection season={tipsheet.season} round={tipsheet.round} />
    </div>
  );
}
