import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlTeamServer, getNrlStatsProfileServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { pct } from "@/lib/format";
import { slugify } from "@/lib/nrlSlug";
import { ChanceChip } from "@/components/ChanceChip";
import { ClubBadge } from "@/components/ClubBadge";
import { FormStrip } from "@/components/FormStrip";
import { ShareButton } from "@/components/ShareButton";
import { VenueSplits } from "@/components/nrl/VenueSplits";
import type { NrlTeamFixture, NrlTeamResult } from "@/lib/types";

/** NRL club profile: ladder slot + record, season snapshot, recent form, how
 *  the AI has fared on this club, upcoming fixtures with the club's win
 *  chance, and every result — each linking to its match page. */

function kickoffLabel(iso: string | null): string {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleString("en-AU", {
    weekday: "short", day: "numeric", month: "short",
    hour: "numeric", minute: "2-digit",
    timeZone: "Australia/Sydney", timeZoneName: "short",
  });
}

const ordinal = (n: number): string => {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th";
  return `${n}${suffix}`;
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  if (!/^\d+$/.test(id)) return { title: `Club — ${APP_NAME}` };
  const data = await getNrlTeamServer(id).catch(() => null);
  if (!data) return { title: `Club — ${APP_NAME}` };
  const { team, ladder, summary, season } = data;
  const title = `${team.name} — NRL ${season} club profile | ${APP_NAME}`;
  const standing = [
    ladder ? `${ordinal(ladder.rank)} on the ladder` : null,
    summary ? `${summary.wins}–${summary.losses}–${summary.draws} record` : null,
  ]
    .filter(Boolean)
    .join(", ");
  const description =
    `${team.name} in the ${season} NRL season` +
    `${standing ? ` — ${standing}` : ""}. Form, results and predictions from the FinalWhistle ML model.`;
  return {
    title, description,
    alternates: { canonical: `/nrl/team/${id}` },
    openGraph: { title, description },
  };
}

export default async function NrlTeamPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const data = await getNrlTeamServer(id);
  if (!data) notFound();
  const { team, ladder, summary, results, upcoming, model, season, disclaimer } = data;
  const statsProfile = await getNrlStatsProfileServer(slugify(team.name)).catch(() => null);

  const record = summary ? `${summary.wins}–${summary.losses}–${summary.draws}` : null;
  const subtitle = [
    ladder ? `${ordinal(ladder.rank)} on the ladder` : null,
    record,
    ladder ? `${ladder.points} pts` : null,
    team.elo_rating != null ? `Elo ${Math.round(team.elo_rating)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const streak = summary?.streak ?? null;
  const form = results.slice(0, 5).map((r) => ({
    opponent: r.opponent ?? "TBC",
    score_for: r.score_for,
    score_against: r.score_against,
    result: r.result,
    date: r.kickoff_utc,
  }));

  return (
    <div className="fade-up mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Link
          href="/nrl/ladder"
          className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground"
        >
          <span aria-hidden>←</span> Ladder
        </Link>
        <ShareButton title={`${team.name} — NRL ${season} profile`} />
      </div>

      {/* Header — badge tile + name + ladder/record subtitle + streak pill */}
      <header className="flex items-center gap-4">
        <span className="grid shrink-0 place-items-center rounded-2xl bg-win/10 p-2.5">
          <ClubBadge name={team.name} size={56} />
        </span>
        <div>
          <h1 className="font-display text-3xl font-extrabold tracking-tight">
            {team.name}
          </h1>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
          {streak && streak.length >= 2 && (
            <span
              className={`mt-1.5 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
                streak.result === "W"
                  ? "bg-win/15 text-lime-deep"
                  : streak.result === "L"
                    ? "bg-loss/15 text-loss"
                    : "bg-draw/15 text-amber-ink"
              }`}
            >
              {streak.length}-game{" "}
              {streak.result === "W" ? "winning" : streak.result === "L" ? "losing" : "drawn"}{" "}
              run
            </span>
          )}
        </div>
      </header>

      {/* Season snapshot — per-game tiles + splits + bookend results */}
      {summary && (
        <section className="glass rounded-2xl p-6">
          <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Season snapshot · {summary.played} games
          </span>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label="Avg scored" value={summary.avg_for.toFixed(1)} />
            <StatTile label="Avg conceded" value={summary.avg_against.toFixed(1)} />
            <StatTile
              label="Avg margin"
              value={`${summary.avg_margin > 0 ? "+" : ""}${summary.avg_margin.toFixed(1)}`}
              tone={summary.avg_margin > 0 ? "up" : summary.avg_margin < 0 ? "down" : undefined}
            />
            {ladder && (
              <StatTile
                label="For/against"
                value={`${ladder.diff > 0 ? "+" : ""}${ladder.diff}`}
                tone={ladder.diff > 0 ? "up" : ladder.diff < 0 ? "down" : undefined}
              />
            )}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border pt-3 text-xs text-muted">
            <span>
              Home{" "}
              <strong className="font-bold tabular-nums text-foreground">
                {summary.home.wins}–{summary.home.losses}–{summary.home.draws}
              </strong>
            </span>
            <span>
              Away{" "}
              <strong className="font-bold tabular-nums text-foreground">
                {summary.away.wins}–{summary.away.losses}–{summary.away.draws}
              </strong>
            </span>
            {summary.biggest_win && (
              <span>
                Biggest win{" "}
                <strong className="font-bold tabular-nums text-foreground">
                  {summary.biggest_win.score_for}–{summary.biggest_win.score_against}
                </strong>{" "}
                vs {summary.biggest_win.opponent ?? "TBC"}
              </span>
            )}
            {summary.biggest_loss && (
              <span>
                Heaviest loss{" "}
                <strong className="font-bold tabular-nums text-foreground">
                  {summary.biggest_loss.score_for}–{summary.biggest_loss.score_against}
                </strong>{" "}
                vs {summary.biggest_loss.opponent ?? "TBC"}
              </span>
            )}
          </div>
        </section>
      )}

      {/* Recent form */}
      <section className="glass rounded-2xl p-6">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          Recent form
        </span>
        <div className="mt-3">
          <FormStrip form={form} />
        </div>
      </section>

      {/* The AI on this club — from the frozen, append-only grading ledger */}
      {model && (
        <section className="glass rounded-2xl p-6">
          <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-lime-deep">
            The ML model on the {team.name}
          </span>
          <p className="mb-4 mt-2 font-display text-lg font-bold leading-snug tracking-tight">
            The model has called {model.called} of {model.graded} graded{" "}
            {team.name} {model.graded === 1 ? "game" : "games"} this season.
          </p>
          <div className="grid grid-cols-3 gap-2">
            <StatTile label="Graded" value={String(model.graded)} />
            <StatTile label="Called right" value={String(model.called)} />
            <StatTile label="Hit rate" value={pct(model.accuracy)} tone="up" />
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Graded from predictions frozen at kickoff — never revised after the game.
          </p>
        </section>
      )}

      {/* Next up — fixtures with the club's win chance */}
      {upcoming.length > 0 && (
        <section>
          <h2 className="mb-3 font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Next up
          </h2>
          <div className="space-y-2">
            {upcoming.map((f) => (
              <FixtureRow key={`${f.round}-${f.match_no}`} fixture={f} season={season} />
            ))}
          </div>
        </section>
      )}

      {/* Results — every finished game, most recent first */}
      {results.length > 0 && (
        <section>
          <h2 className="mb-3 font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Results
          </h2>
          <div className="space-y-2">
            {results.map((r) => (
              <ResultRow key={`${r.round}-${r.match_no}`} result={r} season={season} />
            ))}
          </div>
        </section>
      )}

      {statsProfile ? <VenueSplits splits={statsProfile.venue_splits} /> : null}

      <p className="text-center text-xs leading-relaxed text-muted">{disclaimer}</p>
    </div>
  );
}

function StatTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div className="rounded-2xl bg-win/[0.06] px-2 py-3 text-center">
      <p
        className={`font-display text-xl font-extrabold tabular-nums ${
          tone === "up" ? "text-lime-deep" : tone === "down" ? "text-loss" : "text-foreground"
        }`}
      >
        {value}
      </p>
      <p className="mt-0.5 text-[11px] font-semibold text-muted">{label}</p>
    </div>
  );
}

/** Row wrapper: links to the match page when the round is known (the detail
 *  URL needs the (season, round, match_no) triple). */
function MatchRow({
  season,
  round,
  matchNo,
  children,
}: {
  season: number;
  round: number | null;
  matchNo: number;
  children: React.ReactNode;
}) {
  const className = "glass flex items-center gap-3 rounded-2xl p-3.5";
  return round != null ? (
    <Link href={`/nrl/match/${season}/${round}/${matchNo}`} className={`card-hover ${className}`}>
      {children}
    </Link>
  ) : (
    <div className={className}>{children}</div>
  );
}

function FixtureRow({ fixture: f, season }: { fixture: NrlTeamFixture; season: number }) {
  return (
    <MatchRow season={season} round={f.round} matchNo={f.match_no}>
      <ClubBadge name={f.opponent} size={28} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-display text-[15px] font-semibold">
          {f.was_home ? "vs" : "at"} {f.opponent ?? "TBC"}
        </p>
        <p className="text-xs text-muted">
          Rd {f.round ?? "TBC"} · {kickoffLabel(f.kickoff_utc)}
        </p>
      </div>
      {f.win_prob != null && (
        <ChanceChip prob={f.win_prob} deltaText={null} tone={f.win_prob >= 0.5 ? "up" : "muted"} />
      )}
    </MatchRow>
  );
}

const RESULT_TONE: Record<string, string> = {
  W: "bg-win/15 text-lime-deep",
  D: "bg-draw/15 text-amber-ink",
  L: "bg-loss/15 text-loss",
};

function ResultRow({ result: r, season }: { result: NrlTeamResult; season: number }) {
  return (
    <MatchRow season={season} round={r.round} matchNo={r.match_no}>
      <span
        className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg font-display text-xs font-extrabold ${RESULT_TONE[r.result]}`}
      >
        {r.result}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-display text-[15px] font-semibold">
          {r.was_home ? "vs" : "at"} {r.opponent ?? "TBC"}
        </p>
        <p className="text-xs text-muted">Rd {r.round ?? "TBC"}</p>
      </div>
      {r.model_called != null && (
        <span
          className={`text-xs font-semibold ${r.model_called ? "text-lime-deep" : "text-loss"}`}
          title={r.model_called ? "The ML model called this one" : "The ML model missed this one"}
        >
          <span aria-hidden>{r.model_called ? "✓" : "✕"}</span> ML model
        </span>
      )}
      <span className="font-display text-base font-extrabold tabular-nums">
        {r.score_for}–{r.score_against}
      </span>
    </MatchRow>
  );
}
