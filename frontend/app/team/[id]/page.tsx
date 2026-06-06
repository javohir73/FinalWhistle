"use client";

import Link from "next/link";
import { getTeam } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { FormStrip } from "@/components/FormStrip";
import { Loading, ErrorState } from "@/components/States";

export default function TeamPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const state = useFetch(() => getTeam(id), [id]);

  if (state.status === "loading") return <Loading label="Loading team…" />;
  if (state.status === "error") return <ErrorState message={state.message} />;

  const { team, recent_form, strengths, weaknesses } = state.data;

  return (
    <div className="space-y-6">
      <Link href="/" className="text-sm text-foreground/60 hover:underline">
        ← Home
      </Link>

      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-bold">{team.name}</h1>
        <div className="flex gap-4 text-sm text-foreground/60">
          {team.confederation && <span>{team.confederation}</span>}
          {team.fifa_rank != null && <span>FIFA #{team.fifa_rank}</span>}
          {team.elo_rating != null && <span>Elo {Math.round(team.elo_rating)}</span>}
          {team.is_host && <span className="font-medium text-win">Host</span>}
        </div>
      </header>

      <section className="rounded-xl border border-border p-5">
        <h2 className="mb-3 font-semibold">Recent form</h2>
        <FormStrip form={recent_form} />
      </section>

      <div className="grid gap-5 sm:grid-cols-2">
        <section className="rounded-xl border border-border p-5">
          <h2 className="mb-3 font-semibold">Strengths</h2>
          <ul className="space-y-1 text-sm">
            {strengths.map((s, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-win">✓</span>
                {s}
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-xl border border-border p-5">
          <h2 className="mb-3 font-semibold">Weaknesses</h2>
          <ul className="space-y-1 text-sm">
            {weaknesses.map((w, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-loss">•</span>
                {w}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
