import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNrlLadderServer } from "@/lib/api";
import { LadderTable } from "@/components/LadderTable";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL ladder — FinalWhistle" };

export default async function NrlLadderPage() {
  const ladder = await getNrlLadderServer();
  if (!ladder) notFound();

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">
        NRL ladder · Season {ladder.season}
      </h1>
      <p className="mt-1 text-sm text-muted">Top 8 qualify for the finals.</p>
      <div className="glass mt-6 rounded-2xl p-4">
        <LadderTable rows={ladder.rows} />
      </div>
    </div>
  );
}
