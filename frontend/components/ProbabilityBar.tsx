import type { Probabilities } from "@/lib/types";
import { pct } from "@/lib/format";

interface Props {
  probabilities: Probabilities;
  homeLabel?: string;
  awayLabel?: string;
  showLabels?: boolean;
}

/** Horizontal W/D/L stacked bar — the core visual of a prediction (PRD §12). */
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
        className="flex h-6 w-full overflow-hidden rounded-md text-[10px] font-semibold text-white"
        role="img"
        aria-label={`${homeLabel} win ${pct(home_win)}, draw ${pct(draw)}, ${awayLabel} win ${pct(away_win)}`}
      >
        <div className="flex items-center justify-center bg-win" style={seg(home_win)}>
          {home_win >= 0.12 && pct(home_win)}
        </div>
        <div className="flex items-center justify-center bg-draw text-foreground" style={seg(draw)}>
          {draw >= 0.12 && pct(draw)}
        </div>
        <div className="flex items-center justify-center bg-loss" style={seg(away_win)}>
          {away_win >= 0.12 && pct(away_win)}
        </div>
      </div>
      {showLabels && (
        <div className="mt-1 flex justify-between text-xs text-foreground/60">
          <span>{homeLabel} win</span>
          <span>Draw</span>
          <span>{awayLabel} win</span>
        </div>
      )}
    </div>
  );
}
