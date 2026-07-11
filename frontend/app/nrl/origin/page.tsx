import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getOriginRecordServer, getOriginSeriesServer } from "@/lib/api";
import type { OriginGame } from "@/lib/types";
import { cn } from "@/lib/utils";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "State of Origin predictions — FinalWhistle",
  description:
    "NSW Blues vs QLD Maroons — series score, per-game model predictions and series-winner odds from the FinalWhistle Elo model.",
};

const kickoffFmt = new Intl.DateTimeFormat("en-AU", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Australia/Sydney",
});

function seriesLine(blues: number, maroons: number, drawn: number, winner: string | null) {
  const score = `NSW Blues ${blues} – ${maroons} QLD Maroons${drawn ? ` · ${drawn} drawn` : ""}`;
  if (winner === "drawn") return `Series drawn · ${score}`;
  if (winner) return `${winner} win the series ${winner === "NSW Blues" ? `${blues}–${maroons}` : `${maroons}–${blues}`}`;
  return `Series live · ${score}`;
}

function GameCard({ game }: { game: OriginGame }) {
  const played = game.status === "finished" && game.score_home != null;
  const pred = game.prediction;
  return (
    <div className="glass rounded-2xl p-4">
      <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
        Game {game.round ?? game.match_no}
        {game.venue ? ` · ${game.venue}` : ""}
        {game.neutral ? " · neutral venue" : ""}
      </p>
      <div className="mt-2 flex items-baseline justify-between gap-3">
        <p className="font-display text-lg font-extrabold">
          {game.home ?? "TBC"}{" "}
          <span className="tabular-nums">{played ? game.score_home : ""}</span>
          <span className="mx-2 text-muted">{played ? "–" : "vs"}</span>
          <span className="tabular-nums">{played ? game.score_away : ""}</span>{" "}
          {game.away ?? "TBC"}
        </p>
        {!played && game.kickoff_utc ? (
          <p className="text-xs text-muted">{kickoffFmt.format(new Date(game.kickoff_utc))} AEST</p>
        ) : null}
      </div>
      {pred ? (
        <div className="mt-3">
          <div className="flex h-2 overflow-hidden rounded-full">
            <div className="bg-lime-deep" style={{ width: `${pred.p_home * 100}%` }} />
            <div className="bg-white/25" style={{ width: `${pred.p_draw * 100}%` }} />
            <div className="bg-sky-500" style={{ width: `${pred.p_away * 100}%` }} />
          </div>
          <p className="mt-1 text-xs tabular-nums text-muted">
            {game.home} {(pred.p_home * 100).toFixed(0)}% · draw{" "}
            {(pred.p_draw * 100).toFixed(0)}% · {game.away}{" "}
            {(pred.p_away * 100).toFixed(0)}%
            {pred.expected_margin != null
              ? ` · expected margin ${pred.expected_margin > 0 ? "+" : ""}${pred.expected_margin.toFixed(1)}`
              : ""}
          </p>
        </div>
      ) : null}
    </div>
  );
}

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

export default async function OriginPage({
  searchParams,
}: {
  searchParams: Promise<{ season?: string }>;
}) {
  const { season } = await searchParams;
  const seasonNum = season ? Number(season) : undefined;
  const [series, record] = await Promise.all([
    getOriginSeriesServer(seasonNum).catch(() => null),
    getOriginRecordServer().catch(() => null),
  ]);
  if (!series) notFound();

  const s = series.series;
  return (
    <div>
      <h1 className="font-display text-2xl font-extrabold">
        State of Origin · {series.season}
      </h1>
      <p className="mt-1 text-sm text-muted">
        {seriesLine(s.blues_wins, s.maroons_wins, s.drawn_games, s.winner)}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {series.seasons.map((yr) => (
          <Link
            key={yr}
            href={yr === series.seasons[0] ? "/nrl/origin" : `/nrl/origin?season=${yr}`}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-semibold",
              yr === series.season ? "bg-lime-deep text-black" : "glass text-muted",
            )}
          >
            {yr}
          </Link>
        ))}
      </div>

      <div className="mt-6 grid gap-4">
        {series.games.map((g) => (
          <GameCard key={g.match_no} game={g} />
        ))}
      </div>

      {s.odds ? (
        <section className="mt-8">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
            Series-winner odds
          </h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            <Stat label="NSW Blues" value={`${(s.odds.blues * 100).toFixed(1)}%`} />
            <Stat label="QLD Maroons" value={`${(s.odds.maroons * 100).toFixed(1)}%`} />
            <Stat label="Series drawn" value={`${(s.odds.drawn * 100).toFixed(1)}%`} />
          </div>
        </section>
      ) : null}

      {record ? (
        <section className="mt-8">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
            Model record
          </h2>
          {record.backtest ? (
            <>
              <p className="mt-2 text-xs text-muted">
                Backtest · walk-forward retrodictions over{" "}
                {record.backtest.span[0]}–{record.backtest.span[1]} ({record.backtest.n}{" "}
                games) — not live predictions. A fixed base-rate prior (fitted in
                hindsight) scores{" "}
                {record.backtest.home_prior_log_loss.toFixed(3)} log loss.
              </p>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label="Winner accuracy"
                      value={`${(record.backtest.winner_accuracy * 100).toFixed(1)}%`} />
                <Stat label="Log loss" value={record.backtest.avg_log_loss.toFixed(3)} />
                <Stat label="Brier" value={record.backtest.avg_brier.toFixed(3)} />
                <Stat label="Home-pick baseline"
                      value={`${(record.backtest.home_baseline_accuracy * 100).toFixed(1)}%`} />
              </div>
            </>
          ) : null}
          <p className="mt-4 text-xs text-muted">
            {record.live.evaluated_matches === 0
              ? "No graded live predictions yet — predictions freeze at kickoff from the 2027 series."
              : `Live record: ${record.live.evaluated_matches} graded games · ` +
                `${record.live.winner_accuracy != null ? (record.live.winner_accuracy * 100).toFixed(1) : "—"}% winner accuracy.`}
          </p>
        </section>
      ) : null}

      <p className="mt-8 text-xs text-white/40">{series.disclaimer}</p>
    </div>
  );
}
