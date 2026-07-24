import type { Probabilities } from "@/lib/types";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  probabilities: Probabilities;
  homeLabel?: string;
  awayLabel?: string;
  showLabels?: boolean;
  /** Bar height: "default" (today's h-3), "hero" (prototype feature bar,
   *  h-[7px]), "row" (prototype timeline bar, h-[5px]). Visual only -- the
   *  role="img" + printed-percentage aria-label below is unaffected. */
  size?: "hero" | "row" | "default";
}

const SIZE_HEIGHT: Record<NonNullable<Props["size"]>, string> = {
  hero: "h-[7px]",
  row: "h-[5px]",
  default: "h-3",
};

/** Horizontal W/D/L stacked bar — the signature visual of a prediction. */
export function ProbabilityBar({
  probabilities,
  homeLabel = "Home",
  awayLabel = "Away",
  showLabels = true,
  size = "default",
}: Props) {
  const { home_win, draw, away_win } = probabilities;
  const seg = (w: number) => ({ width: `${Math.max(0, w * 100)}%` });

  return (
    <div>
      <div
        className={cn("flex w-full gap-0.5 overflow-hidden rounded-full", SIZE_HEIGHT[size])}
        role="img"
        aria-label={`${homeLabel} win ${pct(home_win)}, draw ${pct(draw)}, ${awayLabel} win ${pct(away_win)}`}
      >
        <div className="rounded-l-full bg-win" style={seg(home_win)} />
        <div className="bg-draw" style={seg(draw)} />
        <div className="rounded-r-full bg-loss" style={seg(away_win)} />
      </div>
      {showLabels && (
        <div className="mt-2 flex justify-between text-[11px] font-semibold tabular-nums">
          <span className="text-lime-deep">{pct(home_win)}</span>
          <span className="text-draw">{pct(draw)} draw</span>
          <span className="text-loss">{pct(away_win)}</span>
        </div>
      )}
    </div>
  );
}
