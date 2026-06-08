"use client";

import { useState } from "react";
import { getGroups, getKnockoutOdds } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { pct } from "@/lib/format";
import { Flag } from "@/components/Flag";
import { FavoriteStar } from "@/components/FavoriteStar";
import { Reveal } from "@/components/Reveal";
import { ErrorState } from "@/components/States";
import { trackEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import type { Group, TournamentOdds } from "@/lib/types";
import Link from "next/link";

type Tab = "title" | "stage" | "bracket" | "groups";
const TABS: { id: Tab; label: string }[] = [
  { id: "title", label: "Title Odds" },
  { id: "stage", label: "Stage Odds" },
  { id: "bracket", label: "Projected Bracket" },
  { id: "groups", label: "Group Qualifiers" },
];

export default function BracketsPage() {
  const oddsState = useFetch(getKnockoutOdds, []);
  const groupsState = useFetch(getGroups, []);
  const [tab, setTab] = useState<Tab>("title");

  const hasOdds = oddsState.status === "success" && oddsState.data.length > 0;

  return (
    <div className="space-y-8">
      <header className="fade-up">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          Road to the Final
        </h1>
        <p className="mt-2 max-w-xl text-muted">
          From a full-tournament Monte-Carlo — thousands of simulated runs through
          the group stage and the real knockout bracket (top 2 + 8 best third-placed
          teams), giving each nation&apos;s odds of going all the way.
        </p>
        <Link
          href="/my-bracket"
          className="mt-4 inline-flex items-center gap-1.5 rounded-xl border border-win/40 bg-win/10 px-4 py-2 text-sm font-semibold text-win transition hover:bg-win/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
        >
          Build your own bracket <span aria-hidden>→</span>
        </Link>
      </header>

      {/* Tabs */}
      <div role="tablist" aria-label="Bracket views" className="flex flex-wrap gap-2 border-b border-border/60">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => setTab(t.id)}
            className={cn(
              "-mb-px rounded-t-lg border-b-2 px-3 py-2 text-sm font-semibold transition",
              tab === t.id
                ? "border-win text-foreground"
                : "border-transparent text-muted hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Title odds */}
      {tab === "title" && (
        <section role="tabpanel" id="panel-title" aria-labelledby="tab-title">
          {oddsState.status === "error" && <ErrorState message={oddsState.message} />}
          {oddsState.status === "loading" && <SkeletonRow count={4} />}
          {oddsState.status === "success" &&
            (oddsState.data.length === 0 ? (
              <NotReady />
            ) : (
              <Contenders teams={oddsState.data.slice(0, 12)} />
            ))}
        </section>
      )}

      {/* Round-by-round */}
      {tab === "stage" && (
        <section role="tabpanel" id="panel-stage" aria-labelledby="tab-stage">
          {oddsState.status === "loading" && <SkeletonRow count={4} />}
          {oddsState.status === "error" && <ErrorState message={oddsState.message} />}
          {oddsState.status === "success" &&
            (hasOdds ? <RoundTable rows={oddsState.data.slice(0, 16)} /> : <NotReady />)}
        </section>
      )}

      {/* Projected bracket (official R32 seeded with projected qualifiers) */}
      {tab === "bracket" && (
        <section role="tabpanel" id="panel-bracket" aria-labelledby="tab-bracket">
          {groupsState.status === "error" && <ErrorState message={groupsState.message} />}
          {groupsState.status === "loading" && <SkeletonRow count={6} />}
          {groupsState.status === "success" && <ProjectedBracket groups={groupsState.data} />}
        </section>
      )}

      {/* Projected qualifiers per group */}
      {tab === "groups" && (
        <section role="tabpanel" id="panel-groups" aria-labelledby="tab-groups">
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
      )}

      <p className="rounded-xl chip p-4 text-xs leading-relaxed text-muted">
        Each run simulates all 72 group matches, ranks the qualifiers, seeds the
        official Round-of-32 bracket, and plays every knockout tie (draws decided by
        a penalty model). Probabilities are the share of runs in which a team reaches
        that stage. Knockout matches are treated as neutral-venue.
      </p>
    </div>
  );
}

function NotReady() {
  return (
    <p className="rounded-xl chip p-4 text-sm text-muted">
      Tournament simulation hasn&apos;t run yet — check back shortly.
    </p>
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
                onClick={() => trackEvent("bracket_team_click", { team: t.team, from: "title" })}
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
                  onClick={() => trackEvent("bracket_team_click", { team: t.team, from: "stage" })}
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
  const [winner, runnerUp] = group.standings; // table order: top two advance
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
      <Link
        href={`/team/${row.team_id}`}
        onClick={() => trackEvent("bracket_team_click", { team: row.team, from: "groups" })}
        className="min-w-0 flex-1 truncate text-sm font-medium hover:text-win"
      >
        {row.team}
      </Link>
      <span className="text-xs font-semibold tabular-nums text-muted">
        {pct(row.qualification_prob)}
      </span>
    </div>
  );
}

// Official 2026 Round-of-32 pairings (FIFA knockout draw). Each side is either a
// group placement (winner=1, runner-up=2) or a best-third-place slot.
type Slot = { g: string; pos: 1 | 2 } | { third: true };
const R32: { no: number; a: Slot; b: Slot }[] = [
  { no: 73, a: { g: "A", pos: 2 }, b: { g: "B", pos: 2 } },
  { no: 74, a: { g: "E", pos: 1 }, b: { third: true } },
  { no: 75, a: { g: "F", pos: 1 }, b: { g: "C", pos: 2 } },
  { no: 76, a: { g: "C", pos: 1 }, b: { g: "F", pos: 2 } },
  { no: 77, a: { g: "I", pos: 1 }, b: { third: true } },
  { no: 78, a: { g: "E", pos: 2 }, b: { g: "I", pos: 2 } },
  { no: 79, a: { g: "A", pos: 1 }, b: { third: true } },
  { no: 80, a: { g: "L", pos: 1 }, b: { third: true } },
  { no: 81, a: { g: "D", pos: 1 }, b: { third: true } },
  { no: 82, a: { g: "G", pos: 1 }, b: { third: true } },
  { no: 83, a: { g: "K", pos: 2 }, b: { g: "L", pos: 2 } },
  { no: 84, a: { g: "H", pos: 1 }, b: { g: "J", pos: 2 } },
  { no: 85, a: { g: "B", pos: 1 }, b: { third: true } },
  { no: 86, a: { g: "J", pos: 1 }, b: { g: "H", pos: 2 } },
  { no: 87, a: { g: "K", pos: 1 }, b: { third: true } },
  { no: 88, a: { g: "D", pos: 2 }, b: { g: "G", pos: 2 } },
];

function ProjectedBracket({ groups }: { groups: Group[] }) {
  const byLetter = new Map<string, Group>();
  for (const g of groups) {
    const m = g.name.match(/([A-L])\s*$/i);
    if (m) byLetter.set(m[1].toUpperCase(), g);
  }
  // Projected best-eight third-placed teams (each group's 3rd, ranked by table).
  const thirds = groups
    .map((g) => g.standings[2])
    .filter(Boolean)
    .sort(
      (a, b) =>
        b.projected_points - a.projected_points ||
        b.projected_goal_diff - a.projected_goal_diff ||
        b.projected_goals_for - a.projected_goals_for,
    )
    .slice(0, 8);

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        {R32.map((tie) => (
          <div key={tie.no} className="glass rounded-xl p-3">
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">
              Round of 32
            </div>
            <BracketSide slot={tie.a} byLetter={byLetter} />
            <div className="my-1 pl-1 text-[10px] font-bold text-muted">vs</div>
            <BracketSide slot={tie.b} byLetter={byLetter} />
          </div>
        ))}
      </div>

      <div className="rounded-xl chip p-4">
        <div className="mb-2 text-xs font-bold uppercase tracking-wider text-muted">
          Projected best third-placed teams
        </div>
        <div className="flex flex-wrap gap-2">
          {thirds.map((t) => (
            <Link
              key={t.team_id}
              href={`/team/${t.team_id}`}
              onClick={() => trackEvent("bracket_team_click", { team: t.team, from: "thirds" })}
              className="inline-flex items-center gap-1.5 rounded-full bg-surface-2/60 px-2.5 py-1 text-xs font-medium hover:text-win"
            >
              <Flag team={t.team} size={16} /> {t.team}
            </Link>
          ))}
        </div>
        <p className="mt-2.5 text-[11px] leading-relaxed text-muted">
          Winners and runners-up are seeded into the official bracket above. The eight
          best third-placed teams also advance, but which specific tie each one fills is
          assigned at tournament time (per FIFA&apos;s pairing rules), so third-place
          slots are shown generically.
        </p>
      </div>
    </div>
  );
}

function BracketSide({ slot, byLetter }: { slot: Slot; byLetter: Map<string, Group> }) {
  if ("third" in slot) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-surface-2/30 px-2 py-1.5">
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded text-[10px] font-bold text-muted ring-1 ring-border">
          3
        </span>
        <span className="text-sm text-muted">Best third-placed team</span>
      </div>
    );
  }
  const g = byLetter.get(slot.g);
  const row = g?.standings[slot.pos - 1];
  const badge = `${slot.g}${slot.pos}`;
  if (!row) {
    return (
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className="text-sm text-muted">{badge}</span>
      </div>
    );
  }
  return (
    <Link
      href={`/team/${row.team_id}`}
      onClick={() => trackEvent("bracket_team_click", { team: row.team, from: "bracket" })}
      className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:text-win focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
    >
      <span className="grid h-5 w-7 shrink-0 place-items-center rounded bg-win/10 text-[10px] font-bold text-win">
        {badge}
      </span>
      <Flag team={row.team} size={18} />
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.team}</span>
    </Link>
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
