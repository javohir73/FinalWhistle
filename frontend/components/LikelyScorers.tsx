import { pct } from "@/lib/format";
import type { Goalscorer, Goalscorers } from "@/lib/types";

/** Show the top this-many scorers per team (the endpoint returns up to ~8). */
const TOP_N = 5;
/** At/above this 2+ chance, surface a "2+" chip next to the player. */
const NOTABLE_2PLUS = 0.1;

/** "Likely scorers" — per-team top players by chance to score, with anytime-score
 *  %. Two modes: a pre-lineup squad estimate or the sharpened confirmed XI; a
 *  badge says which. Each player's xG is a share of the team's predicted goals
 *  (same Poisson basis as the Goals card). Render only when data is present. */
export function LikelyScorers({
  home,
  away,
  data,
}: {
  home: string;
  away: string;
  data: Goalscorers;
}) {
  const confirmed = data.mode === "lineup";
  return (
    <section className="glass rounded-2xl p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-display text-lg font-bold text-foreground">Likely scorers</h2>
        <span
          className={
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide " +
            (confirmed ? "bg-win/15 text-lime-deep" : "bg-surface-2 text-muted")
          }
        >
          <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
          {confirmed ? "Confirmed XI" : "Squad estimate"}
        </span>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <TeamScorers team={home} players={data.home} />
        <TeamScorers team={away} players={data.away} />
      </div>
    </section>
  );
}

function TeamScorers({ team, players }: { team: string; players: Goalscorer[] }) {
  const top = players.slice(0, TOP_N);
  return (
    <div>
      <p className="mb-2 font-display text-sm font-bold">{team}</p>
      {top.length === 0 ? (
        <p className="text-sm text-muted">No player data yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {top.map((p) => (
            <li key={p.name} className="flex items-center justify-between gap-2 text-sm">
              <span className="flex min-w-0 items-center gap-1.5">
                {p.position && (
                  <span className="shrink-0 text-[11px] font-semibold text-muted">{p.position}</span>
                )}
                <span className="truncate text-foreground">{p.name}</span>
                {p.p_score_2plus >= NOTABLE_2PLUS && (
                  <span className="shrink-0 rounded bg-win/15 px-1.5 py-0.5 text-[10px] font-bold text-lime-deep">
                    2+
                  </span>
                )}
              </span>
              <span className="shrink-0 font-display font-bold tabular-nums text-lime-deep">
                {pct(p.p_score)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
