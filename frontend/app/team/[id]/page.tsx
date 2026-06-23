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
import { TeamLastLineup } from "@/components/TeamLastLineup";
import { ShareButton } from "@/components/ShareButton";

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
  return {
    title, description,
    alternates: { canonical: `/team/${params.id}` },
    openGraph: { title, description },
  };
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

  // `group` is fetched above so the group table link resolves; the AI-outlook
  // card reads from the tournament odds rather than the live standings row.
  void group;
  const teamOdds = odds?.find((o) => o.team_id === team.id) ?? null;
  const fixtures = (allMatches ?? []).filter(
    (m) => m.teams.home === team.name || m.teams.away === team.name,
  );

  // Most-recent finished match for this team → its "Last XI" lineup. Sort
  // finished fixtures by kickoff desc and take the first; undated last.
  const lastFinished = fixtures
    .filter((m) => m.status === "finished")
    .sort((a, b) => (b.kickoff_utc ?? "").localeCompare(a.kickoff_utc ?? ""))[0];
  const lastLineup = lastFinished
    ? {
        matchId: lastFinished.match_id,
        side: (lastFinished.teams.home === team.name ? "home" : "away") as
          | "home"
          | "away",
        opponent:
          lastFinished.teams.home === team.name
            ? lastFinished.teams.away
            : lastFinished.teams.home,
        kickoffUtc: lastFinished.kickoff_utc,
      }
    : null;

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Link href="/groups" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
          <span aria-hidden>←</span> Groups
        </Link>
        <ShareButton title={`${team.name} — World Cup 2026 profile`} />
      </div>

      {/* Header — flag tile + name + group/rank/elo subtitle */}
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <span className="grid shrink-0 place-items-center rounded-2xl bg-win/10 p-2.5">
            <Flag team={team.name} size={56} />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-display text-3xl font-extrabold tracking-tight">
                {team.name}
              </h1>
              <FavoriteStar team={team.name} size={22} />
            </div>
            <p className="mt-1 text-sm text-muted">
              {[
                group_name
                  ? /^group\b/i.test(group_name)
                    ? group_name
                    : `Group ${group_name}`
                  : null,
                team.fifa_rank != null ? `FIFA #${team.fifa_rank}` : null,
                team.elo_rating != null ? `Elo ${Math.round(team.elo_rating)}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {team.is_host && (
              <span className="mt-1.5 inline-block rounded-full bg-gold/15 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-gold ring-1 ring-gold/30">
                Tournament host
              </span>
            )}
          </div>
        </div>
      </header>

      {/* AI outlook — plain-language read + run-deep odds tiles */}
      {teamOdds && (
        <section className="glass rounded-2xl p-6">
          <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-lime-deep">
            AI outlook
          </span>
          <p className="mb-4 mt-2 font-display text-lg font-bold leading-snug tracking-tight">
            {outlookSentence(teamOdds.make_knockout, teamOdds.reach_final, teamOdds.win_title)}
          </p>
          <div className="grid grid-cols-2 gap-2">
            <OutlookTile label="Reach KO" value={teamOdds.make_knockout} />
            <OutlookTile label="Reach semis" value={teamOdds.reach_sf} />
            <OutlookTile label="Reach final" value={teamOdds.reach_final} />
            <OutlookTile label="Win title" value={teamOdds.win_title} />
          </div>
        </section>
      )}

      {/* Recent form — form chips + 2-col strengths / weak points */}
      <section className="glass rounded-2xl p-6">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          Recent form
        </span>
        <div className="mb-5 mt-3">
          <FormStrip form={recent_form} />
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-bold text-lime-deep">↑ Strengths</p>
            <ul className="space-y-1.5 text-sm">
              {strengths.map((s, i) => (
                <li key={i} className="flex gap-2 text-foreground/90">
                  <span className="text-muted" aria-hidden>•</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="mb-2 text-xs font-bold text-loss">↓ Weak points</p>
            <ul className="space-y-1.5 text-sm">
              {weaknesses.map((w, i) => (
                <li key={i} className="flex gap-2 text-foreground/90">
                  <span className="text-muted" aria-hidden>•</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Fixtures */}
      {fixtures.length > 0 && (
        <section>
          <h2 className="mb-3 font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Fixtures
          </h2>
          <TeamFixtures matches={fixtures} teamName={team.name} />
        </section>
      )}

      {/* Last XI — the team's most-recent finished match lineup (display-only,
          official via API-Football). A national side has no canonical formation,
          so this is explicitly the last match's XI, not a generic team shape. */}
      {lastLineup ? (
        <TeamLastLineup
          matchId={lastLineup.matchId}
          side={lastLineup.side}
          opponent={lastLineup.opponent}
          kickoffUtc={lastLineup.kickoffUtc}
        />
      ) : (
        <section>
          <h2 className="mb-3 font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Last XI
          </h2>
          <p className="glass rounded-2xl p-6 text-center text-sm text-muted">
            No recent lineup yet.
          </p>
        </section>
      )}

      {/* Primary CTA — group table */}
      {group_id && (
        <Link
          href={`/groups/${group_id}`}
          className="card-hover flex w-full items-center justify-center gap-1.5 rounded-xl border border-border bg-surface px-4 py-3 font-display text-sm font-bold text-foreground"
        >
          View group table <span aria-hidden>→</span>
        </Link>
      )}
    </div>
  );
}

function OutlookTile({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-2xl bg-win/[0.06] px-2 py-3 text-center">
      <p className="font-display text-xl font-extrabold tabular-nums text-lime-deep">
        {pct(value)}
      </p>
      <p className="mt-0.5 text-[11px] font-semibold text-muted">{label}</p>
    </div>
  );
}

/** One plain-language sentence summarising the model's read on the team. */
function outlookSentence(
  knockout: number | null,
  final: number | null,
  title: number | null,
): string {
  const ko = knockout ?? 0;
  const fin = final ?? 0;
  const win = title ?? 0;
  const knockoutClause =
    ko >= 0.75
      ? "A strong chance to reach the knockouts"
      : ko >= 0.4
        ? "A solid shot at the knockouts"
        : "An outside chance of the knockouts";
  const deepClause =
    win >= 0.1
      ? " — and a real shot at the trophy."
      : fin >= 0.15
        ? " — with the run to the final firmly in reach."
        : fin >= 0.05
          ? " — though a deep run looks a stretch."
          : ".";
  return knockoutClause + deepClause;
}
