"use client";

import { getGroups, getTeams } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct } from "@/lib/format";
import { Flag } from "@/components/Flag";
import { FavoriteStar } from "@/components/FavoriteStar";
import { Reveal } from "@/components/Reveal";
import { ErrorState } from "@/components/States";
import type { Group, Team } from "@/lib/types";
import Link from "next/link";

export default function BracketsPage() {
  const groupsState = useFetch(getGroups, []);
  const teamsState = useFetch(getTeams, []);

  return (
    <div className="space-y-12">
      <header className="fade-up">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          Road to the Final
        </h1>
        <p className="mt-2 max-w-xl text-muted">
          The model&apos;s projected knockout picture — title contenders by strength
          and each group&apos;s likely qualifiers.
        </p>
      </header>

      {/* Title contenders */}
      <section>
        <SectionTitle>Title contenders</SectionTitle>
        {teamsState.status === "error" && <ErrorState message={teamsState.message} />}
        {teamsState.status === "loading" && <SkeletonRow count={4} />}
        {teamsState.status === "success" && (
          <Contenders teams={teamsState.data.slice(0, 8)} />
        )}
      </section>

      {/* Projected qualifiers per group */}
      <section>
        <SectionTitle>Projected group qualifiers</SectionTitle>
        {groupsState.status === "error" && <ErrorState message={groupsState.message} />}
        {groupsState.status === "loading" && <SkeletonRow count={6} />}
        {groupsState.status === "success" && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {groupsState.data.map((g, i) => (
              <Reveal key={g.id} delay={Math.min((i % 6) * 50, 250)}>
                <GroupQualifiers group={g} />
              </Reveal>
            ))}
          </div>
        )}
      </section>

      <p className="rounded-xl chip p-4 text-sm text-muted">
        <span className="font-display font-semibold text-foreground/80">
          Full knockout bracket simulation
        </span>{" "}
        — exact round-by-round matchups and tournament-winner odds — arrives with the
        Monte-Carlo tournament engine in the next release.
      </p>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-4 font-display text-xs font-bold uppercase tracking-[0.2em] text-muted">
      {children}
    </h2>
  );
}

function Contenders({ teams }: { teams: Team[] }) {
  const max = Math.max(...teams.map((t) => t.elo_rating ?? 0), 1);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {teams.map((t, i) => (
        <Reveal key={t.id} delay={Math.min(i * 50, 300)}>
          <div className="glass card-hover flex items-center gap-4 rounded-xl p-4">
            <span
              className={`font-display text-2xl font-extrabold tabular-nums ${
                i === 0 ? "text-gold" : "text-muted/50"
              }`}
            >
              {String(i + 1).padStart(2, "0")}
            </span>
            <Flag team={t.name} size={32} />
            <div className="min-w-0 flex-1">
              <Link
                href={`/team/${t.id}`}
                className="font-display font-bold tracking-tight hover:text-win"
              >
                {t.name}
              </Link>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-win/60 to-win"
                  style={{ width: `${((t.elo_rating ?? 0) / max) * 100}%` }}
                />
              </div>
            </div>
            <span className="font-display text-sm font-bold tabular-nums text-foreground/80">
              {t.elo_rating != null ? Math.round(t.elo_rating) : "—"}
            </span>
            <FavoriteStar team={t.name} />
          </div>
        </Reveal>
      ))}
    </div>
  );
}

function GroupQualifiers({ group }: { group: Group }) {
  const [winner, runnerUp] = group.standings; // sorted by qualification prob desc
  return (
    <div className="glass rounded-2xl p-5">
      <div className="mb-3 font-display text-sm font-bold tracking-tight">
        {group.name}
      </div>
      <div className="space-y-2">
        <QualRow row={winner} badge="1st" accent />
        <QualRow row={runnerUp} badge="2nd" />
      </div>
    </div>
  );
}

function QualRow({
  row,
  badge,
  accent = false,
}: {
  row: Group["standings"][number] | undefined;
  badge: string;
  accent?: boolean;
}) {
  if (!row) return null;
  return (
    <div
      className={`flex items-center gap-2.5 rounded-lg p-2 ${
        accent ? "bg-win/[0.06]" : "bg-surface-2/40"
      }`}
    >
      <span
        className={`grid h-6 w-8 shrink-0 place-items-center rounded text-[10px] font-bold ${
          accent ? "bg-win/15 text-win" : "bg-surface-2 text-muted"
        }`}
      >
        {badge}
      </span>
      <Flag team={row.team} size={22} />
      <Link href={`/team/${row.team_id}`} className="flex-1 truncate text-sm font-medium hover:text-win">
        {row.team}
      </Link>
      <span className="text-xs font-semibold tabular-nums text-muted">
        {pct(row.qualification_prob)}
      </span>
    </div>
  );
}

function SkeletonRow({ count }: { count: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="glass rounded-xl p-4">
          <div className="skeleton h-12 w-full rounded" />
        </div>
      ))}
    </div>
  );
}
