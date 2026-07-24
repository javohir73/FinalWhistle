import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlLadderServer, getNrlProjectionsServer } from "@/lib/api";
import { LadderTable } from "@/components/LadderTable";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL ladder — FinalWhistle" };

export default async function NrlLadderPage() {
  const [ladder, projections] = await Promise.all([
    getNrlLadderServer().catch(() => null),
    getNrlProjectionsServer().catch(() => null),
  ]);
  if (!ladder) notFound();

  const projectionsByTeam = Object.fromEntries(
    (projections?.teams ?? []).map((t) => [t.team, { top8: t.top8, top4: t.top4 }]),
  );

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">
        NRL ladder · Season {ladder.season}
      </h1>
      <p className="mt-1 text-sm text-muted">Top 8 qualify for the finals.</p>
      <div className="glass mt-6 rounded-2xl p-4">
        <LadderTable rows={ladder.rows} projections={projectionsByTeam} />
        <Link href="/nrl/run-home" className="mt-3 inline-block text-xs font-semibold text-lime-deep">
          Predict your run home →
        </Link>
      </div>
    </div>
  );
}
