import type { NrlStatsProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

/** 17-team league tier bands for a season rank: 1-4 Elite, 5-8 Strong,
 *  9-12 Mid, 13+ Struggling. Null (no profile / rank not yet computed)
 *  renders as an em-dash rather than guessing a tier. */
function tier(rank: number | null): { label: string; cls: string } {
  if (rank == null) return { label: "—", cls: "bg-surface-2 text-muted" };
  if (rank <= 4) return { label: "Elite", cls: "bg-win/15 text-lime-deep" };
  if (rank <= 8) return { label: "Strong", cls: "bg-win/10 text-lime-deep" };
  if (rank <= 12) return { label: "Mid", cls: "bg-draw/15 text-amber-ink" };
  return { label: "Struggling", cls: "bg-loss/15 text-loss" };
}

function TierChip({ heading, rank }: { heading: string; rank: number | null }) {
  const t = tier(rank);
  return (
    <div className="rounded-xl bg-surface-2/70 p-3 text-center">
      <div className="text-[11px] uppercase tracking-wider text-muted">{heading}</div>
      <div className="mt-1 text-lg font-extrabold tabular-nums text-foreground">
        {rank == null ? "—" : `#${rank}`}
      </div>
      <span className={cn("mt-1 inline-block rounded-lg px-2 py-0.5 text-xs font-bold", t.cls)}>
        {t.label}
      </span>
    </div>
  );
}

/** Wave 2 "matchup" section content: both clubs' attack/defence season
 *  ranks as tier chips. Pure/presentational -- no fetching (that lives in
 *  MatchupSection.tsx, the client island). */
export function MatchupTiers({
  home,
  away,
}: {
  home: { name: string; profile: NrlStatsProfile | null };
  away: { name: string; profile: NrlStatsProfile | null };
}) {
  return (
    <div className="glass rounded-2xl p-6">
      <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
        Matchup — attack &amp; defence
      </h3>
      <div className="mt-4 grid grid-cols-2 gap-6">
        {[home, away].map((side) => (
          <div key={side.name}>
            <div className="text-sm font-bold text-foreground">{side.name}</div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <TierChip heading="Attack" rank={side.profile?.attack_rank ?? null} />
              <TierChip heading="Defence" rank={side.profile?.defence_rank ?? null} />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-muted">
        Season ranks across all 17 clubs — points scored (attack) and conceded (defence) per game.
      </p>
    </div>
  );
}
