import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getTeamServer,
  getGroupServer,
  getUpcomingMatchesServer,
  getKnockoutOddsServer,
} from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { pct } from "@/lib/format";
import { FormStrip } from "@/components/FormStrip";
import { Flag } from "@/components/Flag";
import { FavoriteStar } from "@/components/FavoriteStar";
import { TeamFixtures } from "@/components/TeamFixtures";

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  const data = await getTeamServer(params.id);
  if (!data) return { title: `Team — ${APP_NAME}` };
  const t = data.team;
  const title = `${t.name} — World Cup 2026 profile | ${APP_NAME}`;
  const description = `${t.name} at the 2026 World Cup: Elo ${
    t.elo_rating != null ? Math.round(t.elo_rating) : "—"
  }, FIFA rank ${t.fifa_rank ?? "—"}, recent form, strengths and weaknesses.`;
  return { title, description, openGraph: { title, description } };
}

export default async function TeamPage({ params }: { params: { id: string } }) {
  const data = await getTeamServer(params.id);
  if (!data) notFound();

  const { team, recent_form, strengths, weaknesses, group_id, group_name } = data;

  // Pull the team's group table, fixtures and tournament odds for the dashboard.
  const [group, allMatches, odds] = await Promise.all([
    group_id ? getGroupServer(group_id) : Promise.resolve(null),
    getUpcomingMatchesServer(),
    getKnockoutOddsServer(),
  ]);

  const standings = group?.standings ?? [];
  const rank = standings.findIndex((r) => r.team_id === team.id);
  const standingRow = rank >= 0 ? standings[rank] : null;
  const teamOdds = odds?.find((o) => o.team_id === team.id) ?? null;
  const fixtures = (allMatches ?? []).filter(
    (m) => m.teams.home === team.name || m.teams.away === team.name,
  );

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <Link href="/groups" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <span aria-hidden>←</span> Groups
      </Link>

      {/* Hero */}
      <header className="glass rounded-2xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Flag team={team.name} size={56} />
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-display text-3xl font-extrabold tracking-tight">
                  {team.name}
                </h1>
                <FavoriteStar team={team.name} size={22} />
              </div>
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

      {/* Tournament outlook — projected group finish + run-deep odds */}
      {(standingRow || teamOdds) && (
        <section className="glass rounded-2xl p-6">
          <h2 className="mb-4 font-display text-lg font-bold">Tournament outlook</h2>
          {standingRow && (
            <div className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-2">
              <Outlook label="Projected finish" value={`${ordinal(rank + 1)}${group_name ? ` · ${group_name}` : ""}`} />
              <Outlook label="Projected points" value={String(standingRow.projected_points)} />
              <Outlook
                label="Advance from group"
                value={pct(standingRow.qualification_prob)}
                accent
              />
            </div>
          )}
          {teamOdds && (
            <div className="space-y-2.5">
              {([
                ["Reach knockouts", teamOdds.make_knockout],
                ["Round of 16", teamOdds.reach_r16],
                ["Quarter-final", teamOdds.reach_qf],
                ["Semi-final", teamOdds.reach_sf],
                ["Final", teamOdds.reach_final],
                ["Win the title", teamOdds.win_title],
              ] as const).map(([label, value]) => (
                <OddsRow key={label} label={label} value={value} />
              ))}
            </div>
          )}
        </section>
      )}

      {fixtures.length > 0 && (
        <section className="glass rounded-2xl p-6">
          <h2 className="mb-3 font-display text-lg font-bold">Fixtures</h2>
          <TeamFixtures matches={fixtures} teamName={team.name} />
        </section>
      )}

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

      {/* Explore — connect the team into the rest of the app */}
      <section>
        <h2 className="mb-3 font-display text-xs font-bold uppercase tracking-[0.2em] text-muted">
          Explore
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {group_id && (
            <HubLink href={`/groups/${group_id}`} label={group_name ?? "Group"} sub="Projected table & odds" />
          )}
          <HubLink href="/brackets" label="Title odds" sub="Run to the final" />
          <HubLink href="/matches" label="All fixtures" sub="Every match prediction" />
        </div>
      </section>
    </div>
  );
}

function HubLink({ href, label, sub }: { href: string; label: string; sub: string }) {
  return (
    <Link
      href={href}
      className="card-hover glass flex items-center justify-between gap-2 rounded-xl px-4 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
    >
      <span className="min-w-0">
        <span className="block truncate font-display text-sm font-bold">{label}</span>
        <span className="block truncate text-xs text-muted">{sub}</span>
      </span>
      <span className="shrink-0 text-win" aria-hidden>→</span>
    </Link>
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

function Outlook({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <div className={`font-display text-2xl font-extrabold tabular-nums ${accent ? "text-win" : ""}`}>
        {value}
      </div>
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}

function OddsRow({ label, value }: { label: string; value: number | null }) {
  const v = value ?? 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-32 shrink-0 text-sm text-foreground/90">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full rounded-full bg-gradient-to-r from-win/70 to-win"
          style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }}
        />
      </div>
      <span className="w-10 shrink-0 text-right text-xs font-semibold tabular-nums text-foreground/80">
        {pct(value)}
      </span>
    </div>
  );
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0]);
}
