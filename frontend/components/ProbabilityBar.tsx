import type { Probabilities } from "@/lib/types";
import { pct } from "@/lib/format";

interface Props {
  probabilities: Probabilities;
  homeLabel?: string;
  awayLabel?: string;
  showLabels?: boolean;
}

/** Horizontal W/D/L stacked bar — the signature visual of a prediction. */
export function ProbabilityBar({
  probabilities,
  homeLabel = "Home",
  awayLabel = "Away",
  showLabels = true,
}: Props) {
  const { home_win, draw, away_win } = probabilities;
  const seg = (w: number) => ({ width: `${Math.max(0, w * 100)}%` });

  return (
    <div>
      <div
        className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full"
        role="img"
        aria-label={`${homeLabel} win ${pct(home_win)}, draw ${pct(draw)}, ${awayLabel} win ${pct(away_win)}`}
      >
        <div
          className="rounded-l-full bg-gradient-to-r from-win/70 to-win"
          style={seg(home_win)}
        />
        <div className="bg-draw/80" style={seg(draw)} />
        <div
          className="rounded-r-full bg-gradient-to-r from-loss to-loss/70"
          style={seg(away_win)}
        />
      </div>
      {showLabels && (
        <div className="mt-2 flex justify-between text-[11px] font-medium tabular-nums">
          <span className="text-win">{pct(home_win)}</span>
          <span className="text-draw">{pct(draw)} draw</span>
          <span className="text-loss">{pct(away_win)}</span>
        </div>
      )}
    </div>
  );
}
