import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNrlRecordServer } from "@/lib/api";

export const revalidate = 300;

export const metadata: Metadata = { title: "NRL model record — FinalWhistle" };

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass rounded-2xl p-4">
      <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </p>
      <p className="mt-1 text-2xl font-extrabold tabular-nums">{value}</p>
    </div>
  );
}

/** Empty state per spec: predictions are frozen but nothing is graded until
 *  the first tracked round finishes. Note: the record endpoint returns 200
 *  even with 0 graded matches, so a null fetch here means a real failure
 *  (not "season hasn't started"). */
export default async function NrlRecordPage() {
  const rec = await getNrlRecordServer().catch(() => null);
  if (!rec) notFound();

  if (rec.evaluated_matches === 0) {
    return (
      <div>
        <h1 className="font-display text-2xl font-extrabold">NRL model record</h1>
        <div className="panel-pitch mt-6 rounded-2xl p-6">
          <p className="font-display text-lg font-bold">Season live — grading starts soon</p>
          <p className="mt-2 max-w-lg text-sm text-white/75">
            Predictions are frozen at kickoff and graded after full time. The record
            appears once the first tracked round completes.
          </p>
          <p className="mt-4 text-xs text-white/50">Model {rec.model_version}</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">NRL model record</h1>
      <p className="mt-1 text-sm text-muted">
        Model {rec.model_version} · {rec.evaluated_matches} graded matches
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Winner accuracy"
              value={rec.winner_accuracy != null ? `${(rec.winner_accuracy * 100).toFixed(1)}%` : "—"} />
        <Stat label="Log loss" value={rec.avg_log_loss?.toFixed(3) ?? "—"} />
        <Stat label="Brier" value={rec.avg_brier?.toFixed(3) ?? "—"} />
        <Stat label="Best streak" value={String(rec.best_streak)} />
      </div>
    </div>
  );
}
