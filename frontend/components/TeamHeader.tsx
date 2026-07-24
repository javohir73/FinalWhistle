import Link from "next/link";
import type { Team, TournamentOdds } from "@/lib/types";
import type { CompetitionId } from "@/lib/sports";
import { Flag } from "@/components/Flag";
import { FavoriteStar } from "@/components/FavoriteStar";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * TeamHeader (Floodlight P2 slice p2-s6): the full-bleed crest banner atop a
 * team page (design/Floodlight Prototype.dc.html, Recon 3 Team Detail). A
 * `.floodlight-glow-left` wash sits behind a `border-b` header that breaks out
 * of the page's max-w-3xl column, edge-to-edge -- the symmetric `-mx`/`px`
 * band matches the layout's `px-4 sm:px-5` gutter exactly, so the header
 * reaches the viewport edge without ever making the body scroll horizontally.
 *
 * Content: a back link into the standings, the crest + Bricolage name +
 * FavoriteStar, a group/rank/Elo meta line, the host badge, and a stat-tile
 * row -- the ML-outlook figures from `teamOdds` when we have them, else the raw
 * Elo / FIFA-rank ratings. The glow is one static radial-gradient, so there's
 * nothing to disable under reduced motion.
 */
export function TeamHeader({
  team,
  groupName,
  comp,
  backHref,
  backLabel,
  teamOdds,
}: {
  team: Team;
  groupName?: string | null;
  comp: CompetitionId;
  backHref: string;
  backLabel: string;
  teamOdds?: TournamentOdds | null;
}) {
  // `comp` is part of the header's contract (league pages pass their own) but
  // the wash is comp-neutral lime today; kept so the accent hook lands here later.
  void comp;

  const meta = [
    groupName
      ? /^group\b/i.test(groupName)
        ? groupName
        : `Group ${groupName}`
      : null,
    team.fifa_rank != null ? `FIFA #${team.fifa_rank}` : null,
    team.elo_rating != null ? `Elo ${Math.round(team.elo_rating)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  // ML-outlook tiles when tournament odds exist; otherwise the two raw ratings.
  // Missing figures are dropped rather than faked, so the row shrinks honestly.
  const tiles = teamOdds
    ? [
        { label: "Reach KO", value: pct(teamOdds.make_knockout), accent: true },
        { label: "Reach final", value: pct(teamOdds.reach_final), accent: true },
        { label: "Win title", value: pct(teamOdds.win_title), accent: true },
      ]
    : ([
        team.elo_rating != null
          ? { label: "Elo", value: String(Math.round(team.elo_rating)), accent: false }
          : null,
        team.fifa_rank != null
          ? { label: "FIFA rank", value: `#${team.fifa_rank}`, accent: false }
          : null,
      ].filter(Boolean) as { label: string; value: string; accent: boolean }[]);

  return (
    <header className="floodlight-glow-left -mx-4 border-b border-border px-4 pb-4 pt-1 sm:-mx-5 sm:px-5">
      <Link
        href={backHref}
        className="inline-flex min-h-[44px] items-center text-sm font-semibold text-foreground/80 transition hover:text-lime-deep"
      >
        <span aria-hidden>{"‹ "}</span>
        {backLabel}
      </Link>

      {/* Crest + Bricolage name + favorite star */}
      <div className="mt-1 flex items-center gap-3.5">
        <Flag team={team.name} size={56} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h1 className="truncate font-display text-2xl font-extrabold tracking-[-0.02em]">
              {team.name}
            </h1>
            <FavoriteStar team={team.name} size={20} />
          </div>
          {meta && <p className="mt-0.5 text-sm text-muted">{meta}</p>}
        </div>
      </div>

      {/* Host badge -- gold pill, amber-ink at 12px bold to clear the a11y floor */}
      {team.is_host && (
        <span className="mt-2.5 inline-block rounded-full bg-gold/15 px-2.5 py-1 text-xs font-bold uppercase tracking-wide text-amber-ink ring-1 ring-gold/30">
          Tournament host
        </span>
      )}

      {/* Stat tiles -- 8.5px labels are labels, not body copy (a11y-exempt) */}
      {tiles.length > 0 && (
        <div className="mt-3.5 flex gap-2">
          {tiles.map((t) => (
            <div
              key={t.label}
              className="flex-1 rounded-[12px] border border-border bg-surface/80 px-2.5 py-2.5"
            >
              <p
                className={cn(
                  "font-display text-[17px] font-extrabold tabular-nums",
                  t.accent ? "text-lime-deep" : "text-foreground",
                )}
              >
                {t.value}
              </p>
              <p className="mt-0.5 text-[8.5px] font-semibold uppercase tracking-[0.06em] text-muted">
                {t.label}
              </p>
            </div>
          ))}
        </div>
      )}
    </header>
  );
}
