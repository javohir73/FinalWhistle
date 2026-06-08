"use client";

import { getGroups, getKnockoutOdds } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct } from "@/lib/format";
import { Flag } from "@/components/Flag";
import { FavoriteStar } from "@/components/FavoriteStar";
import { Reveal } from "@/components/Reveal";
import { ErrorState } from "@/components/States";
import type { Group, TournamentOdds } from "@/lib/types";
import Link from "next/link";

export default function BracketsPage() {
  const oddsState = useFetch(getKnockoutOdds, []);
  const groupsState = useFetch(getGroups, []);

  return (
    <div className="space-y-12">
      <header className="fade-up">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          Road to the Final
        </h1>
        <p className="mt-2 max-w-xl text-muted">
          From a full-tournament Monte-Carlo — thousands of simulated runs through
          the group stage and the real knockout bracket (top 2 + 8 best third-placed
          teams), giving each nation&apos;s odds of going all the way.
        </p>
      </header>

      {/* Title odds */}
      <section>
        <SectionTitle>Title contenders</SectionTitle>
        {oddsState.status === "error" && <ErrorState message={oddsState.message} />}
        {oddsState.status === "loading" && <SkeletonRow count={4} />}
        {oddsState.status === "success" &&
          (oddsState.data.length === 0 ? (
            <p className="rounded-xl chip p-4 text-sm text-muted">
              Tournament simulation hasn&apos;t run yet — check back shortly.
            </p>
          ) : (
            <Contenders teams={oddsState.data.slice(0, 8)} />
          ))}
      </section>

      {/* Round-by-round */}
      {oddsState.status === "success" && oddsState.data.length > 0 && (
        <section>
          <SectionTitle>Run to the final</SectionTitle>
          <RoundTable rows={oddsState.data.slice(0, 16)} />
        </section>
      )}

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

      <p className="rounded-xl chip p-4 text-xs leading-relaxed text-muted">
        Each run simulates all 72 group matches, ranks the qualifiers, seeds the
        official Round-of-32 bracket, and plays every knockout tie (draws decided by
        a penalty model). Probabilities are the share of runs in which a team reaches
        that stage. Knockout matches are treated as neutral-venue.
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

function Contenders({ teams }: { teams: TournamentOdds[] }) {
  const max = Math.max(...teams.map((t) => t.win_title ?? 0), 0.01);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {teams.map((t, i) => (
        <Reveal key={t.team_id} delay={Math.min(i * 50, 300)}>
          <div className="glass card-hover flex items-center gap-4 rounded-xl p-4">
            <span
              className={`font-display text-2xl font-extrabold tabular-nums ${
                i === 0 ? "text-gold" : "text-muted/50"
              }`}
            >
              {String(i + 1).padStart(2, "0")}
            </span>
            <Flag team={t.team} size={32} />
            <div className="min-w-0 flex-1">
              <Link
                href={`/team/${t.team_id}`}
                className="font-display font-bold tracking-tight hover:text-win"
              >
                {t.team}
              </Link>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-win/60 to-win"
                  style={{ width: `${((t.win_title ?? 0) / max) * 100}%` }}
                />
              </div>
            </div>
            <div className="text-right">
              <div className="font-display text-base font-extrabold tabular-nums text-win">
                {pct(t.win_title)}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-muted">to win</div>
            </div>
            <FavoriteStar team={t.team} />
          </div>
        </Reveal>
      ))}
    </div>
  );
}

const COLS: { key: keyof TournamentOdds; label: string }[] = [
  { key: "reach_r16", label: "R16" },
  { key: "reach_qf", label: "QF" },
  { key: "reach_sf", label: "SF" },
  { key: "reach_final", label: "Final" },
  { key: "win_title", label: "Win" },
];

function RoundTable({ rows }: { rows: TournamentOdds[] }) {
  return (
    <div className="glass overflow-x-auto rounded-2xl p-2 sm:p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-muted">
            <th className="px-2 pb-2 text-left font-medium">Team</th>
            {COLS.map((c) => (
              <th key={c.key} className="px-2 pb-2 text-right font-medium">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.team_id} className="border-t border-border/50">
              <td className="py-2.5 pr-2">
                <Link
                  href={`/team/${t.team_id}`}
                  className="flex items-center gap-2.5 hover:text-win"
                >
                  <span className="shrink-0">
                    <Flag team={t.team} size={20} />
                  </span>
                  <span className="min-w-0 font-medium leading-tight">{t.team}</span>
                </Link>
              </td>
              {COLS.map((c) => {
                const v = (t[c.key] as number | null) ?? 0;
                const isWin = c.key === "win_title";
                return (
                  <td
                    key={c.key}
                    className={`px-2 text-right tabular-nums ${
                      isWin ? "font-bold text-win" : "text-foreground/80"
                    }`}
                  >
                    {pct(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
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
      <Link href={`/team/${row.team_id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:text-win">
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
