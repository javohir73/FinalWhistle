import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNrlTipsheetServer } from "@/lib/api";
import { TipsheetBlock } from "@/components/nrl/TipsheetBlock";

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
    </div>
  );
}
