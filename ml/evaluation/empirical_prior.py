"""Empirical scoreline prior — historical frequency tables by Elo-gap bucket.

Phase 3 of the exact-score program (FR-3.1d/e). The Poisson grid knows the
matchup's strength gap but not football's empirical scoreline shape (1-0 and
2-1 are over-represented at some gaps relative to what a Poisson grid puts
there). This module fits F_empirical(scoreline | Elo-gap bucket): how often
each scoreline actually occurred in history, per gap bucket, so a pick policy
can blend "what the model thinks" with "what football actually does".

Leak-free by construction: fit(rows, before=D) counts only matches dated
STRICTLY before D — a table fitted at date D can never contain information from
D onward. The walk-forward harness refits per tournament edition at the
edition's first match date.

Scores are stored FAVORITE-first (the side with the higher pre-match Elo;
home on a tie), so one table serves both home-favorite and away-favorite
matches — callers map cells back to home/away orientation. Goals are clamped
to the grid cap so freak results fold into the edge cell, mirroring
scoreline_metrics._clamp_cell.
"""
from __future__ import annotations

from ml.features.training_rows import _as_date
from ml.models.poisson import MAX_GOALS

#: Default gap-bucket boundaries — buckets [0, 50), [50, 150), [150, +inf).
#: Same segmentation the harness's segment report uses (PRD open question 4).
DEFAULT_BUCKET_BOUNDS = (50.0, 150.0)


class EmpiricalScorePrior:
    """F_empirical(scoreline | Elo-gap bucket), fitted on history before a date."""

    def __init__(self, bucket_bounds=DEFAULT_BUCKET_BOUNDS, max_goals: int = MAX_GOALS):
        self.bucket_bounds = tuple(sorted(float(b) for b in bucket_bounds))
        self.max_goals = max_goals
        n_buckets = len(self.bucket_bounds) + 1
        # counts[bucket][fav_goals][dog_goals] — favorite-oriented scoreline counts.
        self._counts = [
            [[0] * (max_goals + 1) for _ in range(max_goals + 1)]
            for _ in range(n_buckets)
        ]
        self._totals = [0] * n_buckets
        self.n_fitted = 0
        self.fitted_before = None

    def bucket_index(self, gap: float) -> int:
        """Which gap bucket |elo_home - elo_away| falls into (0-based)."""
        for i, bound in enumerate(self.bucket_bounds):
            if gap < bound:
                return i
        return len(self.bucket_bounds)

    def _clamp(self, goals: int) -> int:
        return min(max(goals, 0), self.max_goals)

    def fit(self, rows: list[dict], before) -> "EmpiricalScorePrior":
        """Count favorite-oriented scorelines per gap bucket, STRICTLY before
        `before`. Rows on or after the cutoff are skipped — the no-leakage
        guarantee lives here, not in the caller's filtering."""
        cutoff = _as_date(before)
        for r in rows:
            if _as_date(r["date"]) >= cutoff:
                continue
            gap = abs(r["pre_home"] - r["pre_away"])
            if r["pre_home"] >= r["pre_away"]:  # favorite-first; home on a tie
                fav, dog = r["score_home"], r["score_away"]
            else:
                fav, dog = r["score_away"], r["score_home"]
            b = self.bucket_index(gap)
            self._counts[b][self._clamp(fav)][self._clamp(dog)] += 1
            self._totals[b] += 1
            self.n_fitted += 1
        self.fitted_before = cutoff
        return self

    def prob(self, gap: float, fav_goals: int, dog_goals: int) -> float:
        """Empirical P(favorite scores fav_goals, underdog dog_goals | gap bucket).
        An unpopulated bucket returns 0.0 everywhere, so a blend degrades
        gracefully to the grid-only pick."""
        b = self.bucket_index(gap)
        total = self._totals[b]
        if total == 0:
            return 0.0
        return self._counts[b][self._clamp(fav_goals)][self._clamp(dog_goals)] / total

    def bucket_n(self, gap: float) -> int:
        """How many fitted matches landed in the bucket for this gap."""
        return self._totals[self.bucket_index(gap)]
