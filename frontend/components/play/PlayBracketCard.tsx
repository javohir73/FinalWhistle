import Link from "next/link";
import { CompetitionLogo } from "@/components/CompetitionLogo";
import { Eyebrow } from "@/components/Eyebrow";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The model's predicted champion, hoisted from the top-`win_title` team in the
 *  knockout odds by app/play/page.tsx. Only built when a real probability
 *  exists -- when the simulation hasn't run (every win_title null) or the odds
 *  fetch fails, the card degrades to a plain link rather than print a fabricated
 *  number. `winTitle` is a 0-1 probability (pct() renders the %). */
export interface BracketChampion {
  team: string;
  winTitle: number;
}

/** The Football group's entry into the shipped bracket route (Floodlight P5,
 *  p5-s2). A full-card Floodlight glass link -- eyebrow, title, lime arrow --
 *  that surfaces the predicted champion + title probability when the server page
 *  resolved the knockout odds, and degrades to a plain link when it didn't
 *  (`champion` null). It deliberately does NOT re-implement the bracket: no
 *  AIBracket/OfficialBracket import, no topology -- the tab links into
 *  /football/wc26/bracket, where the real projection lives (the served route --
 *  legacy /brackets only 301s there, so we link the canonical path directly to
 *  drop a redirect hop). `card-hover` (gated on prefers-reduced-motion in
 *  globals.css) carries the only motion; the arrow is a static affordance. */
export function PlayBracketCard({
  champion,
  className,
}: {
  champion: BracketChampion | null;
  className?: string;
}) {
  return (
    <Link
      href="/football/wc26/bracket"
      className={cn("glass card-hover flex items-center gap-3 rounded-2xl p-4", className)}
    >
      <CompetitionLogo competition="wc26" size={42} />
      <div className="min-w-0 flex-1">
        <Eyebrow>World Cup 2026</Eyebrow>
        <p className="mt-1 font-display text-lg font-extrabold tracking-tight">
          Projected knockout bracket
        </p>
        {champion ? (
          <p className="mt-1 text-body text-muted">
            Predicted champion:{" "}
            <span className="font-bold text-foreground">{champion.team}</span> ·{" "}
            <span className="tabular-nums">{pct(champion.winTitle)}</span> to lift the trophy
          </p>
        ) : (
          <p className="mt-1 text-body text-muted">
            The model&apos;s most-likely path through the knockouts, updated as it refreshes.
          </p>
        )}
      </div>
      <span aria-hidden className="shrink-0 font-display text-xl font-extrabold text-lime-deep">
        →
      </span>
    </Link>
  );
}
