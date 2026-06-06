import Link from "next/link";
import type { MatchSummary } from "@/lib/types";
import { formatScore } from "@/lib/format";
import { ProbabilityBar } from "./ProbabilityBar";
import { ConfidenceBadge } from "./ConfidenceBadge";

/** The core dashboard card: matchup, predicted winner, W/D/L bar, score (PRD §12). */
export function MatchCard({ match }: { match: MatchSummary }) {
  const { teams, probabilities, predicted_score, confidence, predicted_winner } = match;

  return (
    <Link
      href={`/match/${match.match_id}`}
      className="block rounded-xl border border-border p-4 transition hover:shadow-md focus:outline-none focus:ring-2 focus:ring-win/40"
    >
      <div className="mb-2 flex items-center justify-between text-xs text-foreground/50">
        <span>{match.group ?? match.stage}</span>
        {confidence && <ConfidenceBadge level={confidence} />}
      </div>

      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold">{teams.home}</span>
        <span className="text-sm text-foreground/50">vs</span>
        <span className="font-semibold">{teams.away}</span>
      </div>

      {probabilities ? (
        <ProbabilityBar
          probabilities={probabilities}
          homeLabel={teams.home}
          awayLabel={teams.away}
          showLabels={false}
        />
      ) : (
        <p className="text-sm text-foreground/50">Prediction pending…</p>
      )}

      <div className="mt-3 flex items-center justify-between text-sm">
        <span className="text-foreground/60">
          Predicted:{" "}
          <strong className="text-foreground">{predicted_winner ?? "—"}</strong>
        </span>
        {predicted_score && (
          <span className="tabular-nums text-foreground/60">
            {formatScore(predicted_score.home, predicted_score.away)}
          </span>
        )}
      </div>
    </Link>
  );
}
