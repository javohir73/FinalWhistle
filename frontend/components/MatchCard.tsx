import Link from "next/link";
import type { MatchSummary } from "@/lib/types";
import { formatScore } from "@/lib/format";
import { ProbabilityBar } from "./ProbabilityBar";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Flag } from "./Flag";

/** The core dashboard card: matchup, predicted winner, W/D/L bar, score. */
export function MatchCard({ match }: { match: MatchSummary }) {
  const { teams, probabilities, predicted_score, confidence, predicted_winner } = match;

  return (
    <Link
      href={`/match/${match.match_id}`}
      className="card-hover glass group block rounded-2xl p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50"
    >
      <div className="mb-3.5 flex items-center justify-between">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {match.group ?? match.stage}
        </span>
        {confidence && <ConfidenceBadge level={confidence} />}
      </div>

      <div className="mb-4 space-y-2.5">
        <TeamRow name={teams.home} />
        <TeamRow name={teams.away} />
      </div>

      {probabilities ? (
        <ProbabilityBar
          probabilities={probabilities}
          homeLabel={teams.home}
          awayLabel={teams.away}
        />
      ) : (
        <p className="text-sm text-muted">Prediction pending…</p>
      )}

      <div className="mt-4 flex items-center justify-between border-t border-border/60 pt-3 text-sm">
        <span className="text-muted">
          Winner{" "}
          <strong className="font-semibold text-foreground">
            {predicted_winner ?? "—"}
          </strong>
        </span>
        {predicted_score && (
          <span className="chip rounded-md px-2 py-0.5 font-display text-sm font-bold tabular-nums text-foreground">
            {formatScore(predicted_score.home, predicted_score.away)}
          </span>
        )}
      </div>
    </Link>
  );
}

function TeamRow({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <Flag team={name} size={24} />
      <span className="font-display text-[15px] font-semibold tracking-tight">
        {name}
      </span>
    </div>
  );
}
