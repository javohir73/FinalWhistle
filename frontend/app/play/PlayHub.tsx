"use client";

import { SPORTS, competitionsForSport, type SportId } from "@/lib/sports";
import type { NrlTipsheet } from "@/lib/types";

interface PlayHubProps {
  /** Current-round NRL tipsheet, server-fetched to seed the NRL group's
   *  season/round. Null when the endpoint has no data yet -- the group still
   *  renders, just without the round line (honest degrade). */
  nrlTipsheet: NrlTipsheet | null;
}

/** The Floodlight "Play" hub (design: Floodlight Implementation Plan, P5) --
 *  one predictions surface that merges the WC26 bracket, league score tips and
 *  NRL round tips, grouped by sport. This slice (p5-s1) stands up the shell:
 *  the eyebrow/title, and one glass-headed section per sport. The actual pick
 *  sections drop into these groups in p5-s2 (Football) and p5-s3 (NRL); the
 *  existing /tips, /brackets and /nrl/tips routes stay live and get linked in
 *  from here. Floodlight skin only -- lime is the sole action colour, numerics
 *  are tabular. Pure render (no window/localStorage) so it's SSR-safe. */
export function PlayHub({ nrlTipsheet }: PlayHubProps) {
  return (
    <div>
      <p className="font-display text-[11px] uppercase tracking-wider text-muted">Predictions</p>
      <h1 className="mt-1 font-display text-3xl font-extrabold">Play</h1>
      <p className="mt-1.5 text-[13px] text-muted">
        Make your picks against the model in one place — grouped by sport, graded on a public record.
      </p>

      <PlayGroup sport="football" />
      <PlayGroup
        sport="nrl"
        seed={nrlTipsheet ? `Round ${nrlTipsheet.round} · ${nrlTipsheet.season}` : null}
      />
    </div>
  );
}

/** One sport's group: a sticky-ish glass heading (the sport label from the
 *  registry) over the competitions that live under it. Placeholder body in
 *  this slice -- filled by the per-sport pick sections in p5-s2/p5-s3. */
function PlayGroup({ sport, seed }: { sport: SportId; seed?: string | null }) {
  const competitions = competitionsForSport(sport);
  const headingId = `play-group-${sport}`;

  return (
    <section className="mt-8" aria-labelledby={headingId}>
      <div className="sticky top-0 z-10 -mx-4 flex items-baseline justify-between gap-3 border-b border-border bg-background/80 px-4 py-2 backdrop-blur-xl">
        <h2 id={headingId} className="font-display text-xl font-extrabold">
          {SPORTS[sport].label}
        </h2>
        {seed != null && <span className="shrink-0 text-xs tabular-nums text-muted">{seed}</span>}
      </div>

      <div className="glass mt-3 rounded-2xl p-4">
        <p className="text-[13px] text-muted">
          {competitions.map((c) => c.label).join(" · ")}
        </p>
        <p className="mt-1.5 text-[13px] text-muted">Picks land here soon.</p>
      </div>
    </section>
  );
}
