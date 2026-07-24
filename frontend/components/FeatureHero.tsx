"use client";

import Link from "next/link";
import type { MatchSummary } from "@/lib/types";
import type { CompetitionId } from "@/lib/sports";
import { Eyebrow, CompEyebrowChip } from "@/components/Eyebrow";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { Flag } from "@/components/Flag";
import { formatScore, topOutcome } from "@/lib/format";
import { isLiveNow } from "@/lib/liveLabel";
import { kickoffTime } from "@/lib/datetime";
import { cn } from "@/lib/utils";

/** The P1 confidence -> color mapping. MEDIUM is amber, so its word is printed
 *  at 12px bold (`text-xs font-bold`) to clear the "amber text only >= 12px
 *  bold" a11y rule; HIGH is lime, LOW muted. */
const CONFIDENCE: Record<
  NonNullable<MatchSummary["confidence"]>,
  { word: string; cls: string }
> = {
  High: { word: "HIGH", cls: "text-lime-deep" },
  Medium: { word: "MEDIUM", cls: "text-amber-ink" },
  Low: { word: "LOW", cls: "text-muted" },
};

/**
 * FeatureHero — the "tonight's feature" match on the home hub (design/Floodlight
 * Prototype.dc.html, Recon 3 Screen 1). A glass panel under a single-radial
 * `.floodlight-glow` wash: the leading side's win probability at display-hero
 * scale in lime, the thin W/D/L bar beneath it, and two equal CTAs into the
 * match page. The bar's printed-% aria-label is the accessible source of truth
 * for the decorative-scale giant number, so both read from the SAME probabilities
 * and never disagree. `match={null}` renders an honest placeholder -- never a
 * fabricated number.
 */
export function FeatureHero({
  match,
  comp,
  tz,
}: {
  match: MatchSummary | null;
  comp: CompetitionId;
  tz?: string;
}) {
  if (!match) {
    return (
      <section className="glass relative overflow-hidden rounded-[16px] p-6">
        <span aria-hidden className="floodlight-glow pointer-events-none absolute inset-0" />
        <p className="relative text-center text-sm text-muted">No featured match right now</p>
      </section>
    );
  }

  const { teams, probabilities, predicted_score, confidence } = match;
  const live = isLiveNow(match);
  // Live matches promote the in-play probabilities (same idiom as the old
  // match-of-day card). The giant number and the bar both read from `probs` so
  // they can never disagree.
  const probs = (live && match.live_probabilities) || probabilities;
  const lead = probs ? Math.max(probs.home_win, probs.draw, probs.away_win) : null;
  const heroPct = lead != null ? Math.round(lead * 100) : null;
  const leader = probs ? topOutcome(probs) : null;
  const leaderLabel =
    leader === "home"
      ? `${teams.home} win`
      : leader === "away"
        ? `${teams.away} win`
        : leader === "draw"
          ? "Draw"
          : "";
  const conf = confidence ? CONFIDENCE[confidence] : null;
  const href = `/match/${match.match_id}`;

  return (
    <section className="glass fade-up relative overflow-hidden rounded-[16px] p-5">
      <span aria-hidden className="floodlight-glow pointer-events-none absolute inset-0" />
      <div className="relative">
        {/* Eyebrow row: league accent chip + lime "tonight's feature", with a
            quiet live/kickoff marker pushed to the right. */}
        <div className="flex items-center gap-2">
          <CompEyebrowChip comp={comp} />
          <Eyebrow tone="lime">Tonight&apos;s feature</Eyebrow>
          {live ? (
            <span className="ml-auto text-[11px] font-bold uppercase tracking-wide text-loss">Live</span>
          ) : match.kickoff_utc && tz ? (
            <span className="ml-auto text-[11px] font-semibold tabular-nums text-muted">
              {kickoffTime(match.kickoff_utc, tz)}
            </span>
          ) : null}
        </div>

        {/* Matchup: home crest 52px, Bricolage names (home / v away), away
            crest 38px at 90% opacity. */}
        <div className="mt-2.5 flex items-center gap-3.5">
          <Flag team={teams.home} size={52} />
          <div className="min-w-0 flex-1 font-display text-[30px] font-extrabold leading-none tracking-[-0.03em]">
            <span className="block truncate">{teams.home}</span>
            <span className="block truncate">
              <span className="text-[17px] text-muted">v</span> {teams.away}
            </span>
          </div>
          <Flag team={teams.away} size={38} className="opacity-90" />
        </div>

        {/* Giant win %: display-hero scale in lime, with a smaller % suffix and
            a two-line caption. */}
        <div className="mt-3.5 flex items-baseline gap-2.5">
          <span className="text-display-hero tabular-nums text-lime-deep">
            {heroPct ?? "—"}
            <span className="text-[0.5em]">%</span>
          </span>
          <span className="text-[11px] font-semibold leading-relaxed text-muted">
            <span className="uppercase tracking-wide">{leaderLabel}</span>
            <br />
            AI most likely:{" "}
            {formatScore(predicted_score?.home ?? null, predicted_score?.away ?? null)}
            {conf && (
              <>
                {" · "}
                <span className={cn("text-xs font-bold", conf.cls)}>{conf.word} CONFIDENCE</span>
              </>
            )}
          </span>
        </div>

        {/* Thin (7px) W/D/L bar. Its printed-% aria-label is the accessible
            source of truth for the giant number above. */}
        {probs && (
          <div className="mt-3">
            <ProbabilityBar
              probabilities={probs}
              homeLabel={teams.home}
              awayLabel={teams.away}
              size="hero"
              showLabels={false}
            />
          </div>
        )}

        {/* Two equal CTAs, both into the match page. Lime primary, outline
            secondary; both 44px tap targets. */}
        <div className="mt-4 flex gap-2.5">
          <Link
            href={href}
            className="flex min-h-[44px] flex-1 items-center justify-center rounded-[12px] bg-win font-display text-sm font-semibold text-background transition hover:brightness-[1.06]"
          >
            Make your pick
          </Link>
          <Link
            href={href}
            className="flex min-h-[44px] flex-1 items-center justify-center rounded-[12px] border border-border font-display text-sm font-semibold text-foreground transition hover:border-win hover:text-lime-deep"
          >
            {heroPct != null ? `Why ${heroPct}%?` : "See the prediction"}
          </Link>
        </div>
      </div>
    </section>
  );
}
