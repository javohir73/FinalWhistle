"use client";

import Link from "next/link";
import { getTeam } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { FormStrip } from "@/components/FormStrip";
import { Flag } from "@/components/Flag";
import { Loading, ErrorState } from "@/components/States";

export default function TeamPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const state = useFetch(() => getTeam(id), [id]);

  if (state.status === "loading") return <Loading label="Loading team…" />;
  if (state.status === "error") return <ErrorState message={state.message} />;

  const { team, recent_form, strengths, weaknesses } = state.data;

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <span aria-hidden>←</span> Home
      </Link>

      {/* Hero */}
      <header className="glass rounded-2xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Flag team={team.name} size={56} />
            <div>
              <h1 className="font-display text-3xl font-extrabold tracking-tight">
                {team.name}
              </h1>
              {team.is_host && (
                <span className="mt-1 inline-block rounded-full bg-gold/15 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-gold ring-1 ring-gold/30">
                  Tournament host
                </span>
              )}
            </div>
          </div>
          <div className="flex gap-5">
            <Stat label="Confederation" value={team.confederation ?? "—"} />
            <Stat label="FIFA rank" value={team.fifa_rank != null ? `#${team.fifa_rank}` : "—"} />
            <Stat label="Elo" value={team.elo_rating != null ? String(Math.round(team.elo_rating)) : "—"} />
          </div>
        </div>
      </header>

      <section className="glass rounded-2xl p-6">
        <h2 className="mb-3 font-display text-lg font-bold">Recent form</h2>
        <FormStrip form={recent_form} />
      </section>

      <div className="grid gap-5 sm:grid-cols-2">
        <section className="glass rounded-2xl p-6">
          <h2 className="mb-3 font-display text-lg font-bold text-win">Strengths</h2>
          <ul className="space-y-2 text-sm">
            {strengths.map((s, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-win" aria-hidden>↗</span>
                <span className="text-foreground/90">{s}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="glass rounded-2xl p-6">
          <h2 className="mb-3 font-display text-lg font-bold text-loss">Weaknesses</h2>
          <ul className="space-y-2 text-sm">
            {weaknesses.map((w, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-loss" aria-hidden>↘</span>
                <span className="text-foreground/90">{w}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <div className="font-display text-xl font-extrabold tabular-nums">{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}
