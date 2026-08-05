"""Benchmark the club engine's Over/Under 2.5 book against the closing line.

Pre-registration: `docs/experiments/2026-07-30-d0b-totals-market/
PRE-REGISTRATION.md`, committed alone in `aa7a445` with corrections appended in
`1e207a6`, both before this module existed.

Why this exists
---------------
`base` is the only engine parameter this repository has ever gated on a totals
metric, and both of its shipped per-league overrides were justified against a
**constant** — `pipeline/leagues.py` says so in its own comments. A constant is
a floor, not a yardstick. D0 recovered the 1X2 closing line; the totals closing
line has never been computed here at all, because #202's CSV cache was built
with ``usecols=[Date,HomeTeam,AwayTeam,FTHG,FTAG]`` and dropped the over/under
columns exactly as it dropped the 1X2 ones.

Three things this module will NOT let a caller do
-------------------------------------------------
**Read a favourable number as an edge.** T1.1 selected `base` on O/U 2.5 log
loss over seasons 1718-2425; this scores 1920-2425, a strict subset. The
shipped model column is therefore in-sample on this exact metric.
:func:`score_totals` requires a ``control_p`` column and reports both, because
the honest reading is the *difference* between the in-sample and out-of-sample
model columns, not the level of either.

**Pool two markets.** Every matched row carries its ``odds_basis``, and
:func:`totals_market_basis` returns ``"mixed(...)"`` rather than a
reassuring single label when a run has scored more than one.

**Silently mis-orient the market.** ``devig2`` is positional and unlabeled;
swapping its arguments inverts the market column and makes the model look good
against a mirror-image book. :func:`market_p_over` exists so that ordering is
written down once, next to a test that checks the semantics rather than just
that the pair sums to 1.

Pure module — no DB, no network, no app imports. Orchestration lives in
`pipeline/run_club_totals_benchmark.py`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as date_type
from typing import Sequence

from ml.evaluation.club_walkforward import (
    ClubMatch,
    EloConfig,
    GridConfig,
    totals_probabilities,
)
from ml.evaluation.market_benchmark import devig2

_EPS = 1e-12

#: Cluster keys :func:`clustered_deltas` knows how to build. ``iso_week`` is
#: the pre-registered PRIMARY (§11): six seasons give only six season-clusters
#: per league, and a six-cluster percentile bootstrap under-covers badly, while
#: the calendar week gives ~200 and respects the short-range correlation
#: between matches sharing a rating snapshot. ``season`` is reported alongside
#: as the pre-declared sensitivity, never as the headline.
CLUSTER_KEYS = ("iso_week", "season")


@dataclass(frozen=True)
class MatchedTotal:
    """One match where a model and a market over/under probability both exist.

    ``control_p_over`` is the same match scored under the pre-override global
    ``base`` (`club_baseline_params_for`). It is not optional: without it the
    in-sample advantage described in the module docstring is unmeasurable, and
    the shipped column alone cannot be interpreted.
    """

    date: date_type
    season: str
    home: str
    away: str
    model_p_over: float
    control_p_over: float
    market_p_over: float
    label: int  # 1 = over, 0 = under
    odds_basis: str
    odds_source: str
    line: float

    @property
    def iso_week(self) -> str:
        """``YYYY-Www``. The pre-registered primary resampling cluster."""
        y, w, _ = self.date.isocalendar()
        return f"{y}-W{w:02d}"


def market_p_over(odds_over: float, odds_under: float) -> float:
    """De-vigged P(over) from an (over, under) decimal price pair.

    A one-line wrapper whose entire job is to fix the argument order in one
    place. ``devig2`` is positional and returns ``(p_a, p_b)`` for
    ``(odds_a, odds_b)``, so passing the under price first silently returns
    P(under) labelled as P(over) — and since the two are both plausible
    probabilities near 0.5, nothing downstream would look wrong.
    """
    p_over, _p_under = devig2(odds_over, odds_under)
    return p_over


def ou_label(goals_home: int, goals_away: int, line: float = 2.5) -> int:
    """1 if the total beat ``line``, else 0.

    ``ml.evaluation.market_benchmark.ou25_label`` hardcodes 2.5; this takes the
    line from the odds family so a future 3.5 book cannot be scored against a
    2.5 label.
    """
    return 1 if (goals_home + goals_away) > line else 0


def binary_log_loss(p: float, y: int) -> float:
    """NLL of a binary outcome, clipped. Positive; lower is better."""
    p = min(max(p, _EPS), 1.0 - _EPS)
    return -math.log(p if y == 1 else 1.0 - p)


def build_matched_totals(
    matches: Sequence[ClubMatch],
    pre: Sequence[tuple[float, float]],
    elo: EloConfig,
    served: GridConfig,
    control: GridConfig,
    priced: Sequence[dict],
    line: float = 2.5,
) -> tuple[list[MatchedTotal], list[dict]]:
    """Join model probabilities onto priced rows. Returns (matched, unpriced).

    ``matches``/``pre`` cover the FULL replay window including seasons with no
    closing totals family — those seasons are burn-in for the ratings and are
    never scored. ``priced`` covers only the files that carry the market.

    The join key is ``(date, home, away)``. Both sides originate in the same
    football-data.co.uk CSVs, so the names agree exactly and no alias table is
    needed; a key that fails to join is therefore a real defect and is returned
    rather than dropped, so the caller can assert on it.

    Both model columns are computed in one pass over the same replay: the
    ratings do not depend on ``base``, only the grid does.
    """
    if len(matches) != len(pre):
        raise ValueError(f"matches/pre length mismatch: {len(matches)} vs {len(pre)}")

    # The model must be priced at the line the market and the label use. This
    # used to take ``line`` from the signature while label and market came from
    # ``rec["line"]`` — harmless while every family is 2.5, and a silent
    # mispricing the moment one is not. Exactly the mismatch ``ou_label``'s
    # docstring claims to prevent, so it is now checked rather than documented.
    rec_lines = {r["line"] for r in priced}
    if len(rec_lines) > 1:
        raise ValueError(
            f"priced rows mix over/under lines {sorted(rec_lines)}; the model "
            "column can only be priced at one line per run"
        )
    if rec_lines and (only := next(iter(rec_lines))) != line:
        line = only

    served_p = totals_probabilities(matches, pre, elo, served, line)
    control_p = totals_probabilities(matches, pre, elo, control, line)

    by_key: dict[tuple, tuple[int, ClubMatch]] = {}
    for i, m in enumerate(matches):
        if not m.date:
            continue
        key = (m.date, m.home, m.away)
        if key in by_key:
            # A dict index silently overwrites, which would drop a match AND
            # still report unjoined == 0 — a coverage claim that is true only
            # because the evidence for its falsity was overwritten.
            raise ValueError(
                f"duplicate match key {key} in the replay window; the join "
                "index would silently drop one of them"
            )
        by_key[key] = (i, m)

    matched: list[MatchedTotal] = []
    unpriced: list[dict] = []
    for rec in priced:
        key = (rec["date"].isoformat(), rec["home_team"], rec["away_team"])
        hit = by_key.get(key)
        if hit is None:
            unpriced.append(rec)
            continue
        i, m = hit
        matched.append(
            MatchedTotal(
                date=rec["date"],
                season=m.season,
                home=m.home,
                away=m.away,
                model_p_over=served_p[i],
                control_p_over=control_p[i],
                market_p_over=market_p_over(rec["odds_over"], rec["odds_under"]),
                label=ou_label(m.goals_home, m.goals_away, rec["line"]),
                odds_basis=rec["odds_basis"],
                odds_source=rec["odds_source"],
                line=rec["line"],
            )
        )
    return matched, unpriced


def totals_market_basis(matched: Sequence[MatchedTotal]) -> str:
    """What market was actually scored — never a comforting default.

    Returns ``"closing (AvgC)"`` for a clean run, ``"MIXED(...)"`` when a run
    pooled more than one basis or family, and ``"unknown"`` for an empty one.
    A header that says "closing" when a third of the rows were pre-closing is
    D0's A3 defect; this makes that state unrepresentable in the label.
    """
    if not matched:
        return "unknown"
    bases = sorted({m.odds_basis for m in matched})
    sources = sorted({m.odds_source for m in matched})
    if len(bases) == 1 and len(sources) == 1:
        return f"{bases[0]} ({sources[0]})"
    return "MIXED(" + "/".join(bases) + " via " + "/".join(sources) + ")"


def constant_rate(matched: Sequence[MatchedTotal], fit_seasons: Sequence[str]) -> float:
    """Over-rate on ``fit_seasons`` only — the constant baseline's parameter.

    Fitting on the scored sample would flatter the constant and understate
    every predictor measured against it, so the caller passes an explicit
    season list and :func:`score_totals` asserts it is disjoint from the scored
    seasons.
    """
    fit = [m for m in matched if m.season in set(fit_seasons)]
    if not fit:
        raise ValueError(f"no matched rows in fit seasons {sorted(set(fit_seasons))}")
    return sum(m.label for m in fit) / len(fit)


def clustered_deltas(
    matched: Sequence[MatchedTotal],
    deltas: Sequence[float],
    by: str = "iso_week",
) -> dict[str, list[float]]:
    """Bucket per-match deltas by cluster key, for ``season_clustered_ci``.

    ``season_clustered_ci`` resamples whichever keys it is given, so passing
    week-keyed buckets makes it a week-clustered bootstrap with no change to
    that function.
    """
    if by not in CLUSTER_KEYS:
        raise ValueError(f"unknown cluster key {by!r}; expected one of {CLUSTER_KEYS}")
    if len(matched) != len(deltas):
        raise ValueError(f"matched/deltas length mismatch: {len(matched)} vs {len(deltas)}")
    out: dict[str, list[float]] = {}
    for m, d in zip(matched, deltas):
        out.setdefault(m.iso_week if by == "iso_week" else m.season, []).append(d)
    return out


def _metrics(probs: Sequence[float], labels: Sequence[int]) -> dict:
    n = len(labels)
    ll = sum(binary_log_loss(p, y) for p, y in zip(probs, labels)) / n
    brier = sum((p - y) ** 2 for p, y in zip(probs, labels)) / n
    # Strict > 0.5 rather than round(): banker's rounding sends an exact 0.5 to
    # 0, which is a coin-flip resolved by a float convention nobody chose.
    acc = sum(1 for p, y in zip(probs, labels) if (1 if p > 0.5 else 0) == y) / n
    return {"log_loss": ll, "brier": brier, "accuracy": acc}


def score_totals(
    matched: Sequence[MatchedTotal],
    fit_seasons: Sequence[str],
    scored_seasons: Sequence[str],
) -> dict:
    """The phase's headline table for one league. Selects nothing.

    ``fit_seasons`` parameterize the constant baseline; ``scored_seasons`` are
    what every predictor is measured on. They must be disjoint, and that is
    enforced here rather than trusted to the caller — a constant fitted on the
    data it is scored on would beat both the model and the market for reasons
    that have nothing to do with football.

    Returns per-predictor metrics plus the two paired differences that matter:
    ``model_minus_market`` (negative = model closer to reality than the closing
    line) and ``model_minus_control`` (the in-sample advantage of the shipped
    `base` override, NOT a measurement of skill).
    """
    fit_set, scored_set = set(fit_seasons), set(scored_seasons)
    overlap = fit_set & scored_set
    if overlap:
        raise ValueError(
            f"constant baseline would be fitted in-sample: seasons {sorted(overlap)} "
            "appear in both fit_seasons and scored_seasons"
        )
    rate = constant_rate(matched, fit_seasons)
    rows = [m for m in matched if m.season in scored_set]
    if not rows:
        raise ValueError(f"no matched rows in scored seasons {sorted(scored_set)}")

    labels = [m.label for m in rows]
    model = [m.model_p_over for m in rows]
    control = [m.control_p_over for m in rows]
    market = [m.market_p_over for m in rows]
    const = [rate] * len(rows)

    def paired(a: list[float], b: list[float]) -> list[float]:
        return [binary_log_loss(x, y) - binary_log_loss(z, y)
                for x, z, y in zip(a, b, labels)]

    d_mm = paired(model, market)
    d_mc = paired(model, control)
    d_km = paired(market, const)
    # The comparison the first cut computed as a difference of two LEVELS and
    # therefore reported with no uncertainty at all. `pipeline/leagues.py`
    # justifies both shipped `base` overrides by this exact quantity, so it
    # needs an interval like every other claim, and it turns out not to
    # survive one.
    d_mk = paired(model, const)

    return {
        "n_matches": len(rows),
        "n_fit": sum(1 for m in matched if m.season in fit_set),
        "market_basis": totals_market_basis(rows),
        "constant_rate": rate,
        "over_rate_scored": sum(labels) / len(labels),
        "model": _metrics(model, labels),
        "control": _metrics(control, labels),
        "market": _metrics(market, labels),
        "constant": _metrics(const, labels),
        # Negative = model beats market. Positive = model behind the line.
        "model_minus_market": sum(d_mm) / len(d_mm),
        # Negative = the shipped override is closer to the market than the
        # pre-override global. IN-SAMPLE for the model; not an edge.
        "model_minus_control": sum(d_mc) / len(d_mc),
        # Negative = the model beats a constant. THE defect metric #202 cited.
        "model_minus_constant": sum(d_mk) / len(d_mk),
        # How much the closing line knows about totals beyond the base rate.
        # The denominator that turns a raw gap into a share of the budget.
        "market_minus_constant": sum(d_km) / len(d_km),
        "rows": rows,
        "deltas_model_minus_market": d_mm,
        "deltas_model_minus_control": d_mc,
        "deltas_model_minus_constant": d_mk,
        "deltas_market_minus_constant": d_km,
    }


def information_share(result: dict) -> float | None:
    """Share of the closing line's totals information the model captures.

    ``1 - (model - market) / (constant - market)``. Returns ``None`` when the
    market does not beat the constant, because the ratio is then a division by
    a quantity that is not an information budget at all — reporting a
    percentage of it would be a number with no referent.

    **A point estimate of this is nearly meaningless on its own.** It is a
    ratio of two noisy paired means, so its sampling distribution is wide and
    skewed — see :func:`information_share_ci`, and never quote the point
    estimate without it.
    """
    budget = -result["market_minus_constant"]  # constant LL - market LL
    if budget <= 0:
        return None
    return 1.0 - (result["model_minus_market"] / budget)


def information_share_ci(
    rows: Sequence[MatchedTotal],
    d_model_minus_market: Sequence[float],
    d_market_minus_constant: Sequence[float],
    *,
    by: str = "iso_week",
    n_bootstrap: int = 2000,
    seed: int = 26,
) -> dict:
    """Cluster bootstrap for :func:`information_share`.

    Resamples whole clusters and recomputes the RATIO inside each resample, so
    the interval reflects the noise in both the gap and the budget. Draws where
    the resampled budget is non-positive have no share defined at all; they are
    counted and reported as ``n_undefined`` rather than dropped silently,
    because a budget that can vanish under resampling is the honest reason a
    share cannot be quoted to a tenth of a percent.
    """
    import random as _random

    if not (len(rows) == len(d_model_minus_market) == len(d_market_minus_constant)):
        raise ValueError("rows and both delta series must be the same length")
    buckets: dict[str, list[tuple[float, float]]] = {}
    for r, a, b in zip(rows, d_model_minus_market, d_market_minus_constant):
        buckets.setdefault(r.iso_week if by == "iso_week" else r.season, []).append((a, b))

    keys = sorted(buckets)
    rng = _random.Random(seed)
    shares: list[float] = []
    undefined = 0
    for _ in range(n_bootstrap):
        pairs = [v for k in (keys[rng.randrange(len(keys))] for _ in keys)
                 for v in buckets[k]]
        gap = sum(a for a, _ in pairs) / len(pairs)
        budget = -sum(b for _, b in pairs) / len(pairs)
        if budget <= 0:
            undefined += 1
            continue
        shares.append(1.0 - gap / budget)

    if not shares:
        return {"ci95": None, "n_undefined": undefined, "n_clusters": len(keys)}
    shares.sort()
    lo = shares[int(0.025 * len(shares))]
    hi = shares[min(len(shares) - 1, int(0.975 * len(shares)))]
    return {"ci95": (lo, hi), "n_undefined": undefined, "n_clusters": len(keys)}
