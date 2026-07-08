"""Build enriched backtest rows from the database.

Replays Elo over all historical matches and attaches each match's date and
competition, producing the leak-free rows the pure backtest harness consumes.

Model v2 (docs/MODEL-V2-DESIGN.md §5, C1) also needs a per-side residual
LEDGER on each row: the team's own (gf_residual, ga_residual) history from
ALL of its STRICTLY PRIOR matches, for the form channel to decay-average over.
Residuals are measured against the model's own pre-match expected goals (the
same Elo -> lambda mapping predict_match uses), so they are already
opponent-quality-adjusted and carry no information from the match they are
attached to.
"""
from __future__ import annotations

from collections import defaultdict, deque

from sqlalchemy.orm import Session

from app.models import HistoricalMatch
from ml.models.params import load_params
from ml.models.poisson import expected_goals_from_elo
from ml.ratings.elo import HOME_ADVANTAGE, MatchInput, replay_with_prematch

# Cap on how many prior matches feed a team's residual ledger. 15 is plenty
# for a decayed mean (ml/ratings/form.py) and keeps every row's payload small.
LEDGER_CAP = 15


def build_enriched_rows(
    db: Session, base: float | None = None, beta: float | None = None
) -> list[dict]:
    """Leak-free rows for the backtest/tuning/experiment harnesses.

    `base`/`beta` parameterize the expected-goals mapping used to compute the
    residual ledgers (ledger_home/ledger_away) — the variant that later reads
    them decides which goals params represent "what the model expected", so
    callers may override. Default to the SERVED goals params
    (ml.models.params.load_params()) rather than the v0.1 constants: every
    ledger builder in the repo must measure residuals on the same scale the
    model actually serves predictions on, or an ablation comparing "with
    form" vs "without" is comparing apples measured on different scales
    (model v2 review finding).
    """
    served = load_params()
    base = served.base if base is None else base
    beta = served.beta if beta is None else beta
    ordered = (
        db.query(HistoricalMatch)
        .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
        .all()
    )
    inputs = [
        MatchInput(
            home_id=m.team_a_id,
            away_id=m.team_b_id,
            score_home=m.score_a,
            score_away=m.score_b,
            competition=m.competition,
            is_neutral=m.is_neutral,
        )
        for m in ordered
    ]
    rows, _ = replay_with_prematch(inputs)
    # Attach date + competition (same order as `ordered`).
    for row, orm in zip(rows, ordered):
        row["date"] = orm.date
        row["competition"] = orm.competition

    # Second pass, in the same oldest-first order: snapshot each side's ledger
    # BEFORE the match, then append the match's own residual for later rows.
    # Reading the ledger before appending guarantees a match's own result can
    # never enter its own ledger — only matches strictly earlier in the walk.
    ledgers: dict[int, deque] = defaultdict(lambda: deque(maxlen=LEDGER_CAP))
    for row in rows:
        home_id, away_id = row["home_id"], row["away_id"]
        row["ledger_home"] = list(ledgers[home_id])
        row["ledger_away"] = list(ledgers[away_id])

        adv = 0.0 if row["is_neutral"] else HOME_ADVANTAGE
        lam_home, lam_away = expected_goals_from_elo(
            row["pre_home"], row["pre_away"], adv, base, beta,
        )
        ledgers[home_id].append((row["score_home"] - lam_home, row["score_away"] - lam_away))
        ledgers[away_id].append((row["score_away"] - lam_away, row["score_home"] - lam_home))

    return rows
