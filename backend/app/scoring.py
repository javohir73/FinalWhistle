"""Bracket scoring — backend-owned (the client score is never trusted).

Points (simple and legible):
  * group match, correct outcome ............... 3
  * knockout R32/R16/QF, correct winner ........ 5  ("team advances")
  * semi-final, correct winner (finalist) ...... 10
  * final, correct winner (champion) ........... 20

Pure `score_bracket` is the tested core; `recompute_scores` wires it to the DB
and assigns ranks. Group results come from finished group matches; knockout
results are passed in (keyed by official match number) once those games exist.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Bracket, BracketScore, Match

# Official knockout match numbers by round (mirrors the bracket structure).
R32_NOS = list(range(73, 89))          # 73..88
R16_NOS = [89, 90, 91, 92, 93, 94, 95, 96]
QF_NOS = [97, 98, 99, 100]
SF_NOS = [101, 102]
FINAL_NO = 104

GROUP_PTS = 3
ADVANCE_PTS = 5      # R32/R16/QF
FINALIST_PTS = 10    # SF winner
CHAMPION_PTS = 20    # final winner

_ADVANCE_NOS = set(R32_NOS + R16_NOS + QF_NOS)

Outcome = str  # "home" | "draw" | "away"


def score_bracket(
    group_picks: dict[int, Outcome],
    group_results: dict[int, Outcome],
    knockout_picks: dict[int, int],
    knockout_results: dict[int, int],
) -> dict:
    """Score one bracket. Picks are keyed by match id (group) / match number
    (knockout); results likewise. A pick only scores when a result exists."""
    group_points = GROUP_PTS * sum(
        1 for mid, p in group_picks.items() if group_results.get(mid) == p
    )

    def correct(no: int) -> bool:
        res = knockout_results.get(no)
        return res is not None and knockout_picks.get(no) == res

    knockout_points = (
        ADVANCE_PTS * sum(1 for no in _ADVANCE_NOS if correct(no))
        + FINALIST_PTS * sum(1 for no in SF_NOS if correct(no))
    )
    champion_bonus = CHAMPION_PTS if correct(FINAL_NO) else 0

    return {
        "group_points": group_points,
        "knockout_points": knockout_points,
        "champion_bonus": champion_bonus,
        "total_points": group_points + knockout_points + champion_bonus,
    }


def group_results_from_db(db: Session) -> dict[int, Outcome]:
    """Outcomes of finished group matches, keyed by match id."""
    out: dict[int, Outcome] = {}
    finished = (
        db.query(Match)
        .filter(Match.stage == "group", Match.status == "finished")
        .all()
    )
    for m in finished:
        if m.score_home is None or m.score_away is None:
            continue
        out[m.id] = (
            "home" if m.score_home > m.score_away
            else "away" if m.score_away > m.score_home
            else "draw"
        )
    return out


def knockout_results_from_db(db: Session) -> dict[int, int]:
    """Finished KO matches -> winning team id, keyed by official match_no.
    Winner = higher score; if level, higher penalty tally; omit if still tied.
    (match_no 103 is resolved like any other KO row but carries no points —
    the ADVANCE/FINALIST/CHAMPION sets already exclude 103.)"""
    out: dict[int, int] = {}
    finished = (
        db.query(Match)
        .filter(Match.stage != "group", Match.status == "finished", Match.match_no.isnot(None))
        .all()
    )
    for m in finished:
        if m.team_home_id is None or m.team_away_id is None:
            continue
        winner: int | None = None
        if m.score_home is not None and m.score_away is not None:
            if m.score_home > m.score_away:
                winner = m.team_home_id
            elif m.score_away > m.score_home:
                winner = m.team_away_id
        if winner is None and m.penalty_home is not None and m.penalty_away is not None:
            if m.penalty_home > m.penalty_away:
                winner = m.team_home_id
            elif m.penalty_away > m.penalty_home:
                winner = m.team_away_id
        if winner is not None:
            out[m.match_no] = winner
    return out


def recompute_scores(db: Session, knockout_results: dict[int, int] | None = None) -> int:
    """Recompute every bracket's score and rank. Returns the number scored.

    `knockout_results` maps official match number -> winning team id (supplied by
    the results job once knockout games are played). Group results are read from
    the DB. Safe to run any time; pre-tournament everything scores 0.
    """
    knockout_results = knockout_results or {}
    group_results = group_results_from_db(db)
    now = datetime.now(timezone.utc)

    scored: list[tuple[BracketScore, int]] = []
    for b in db.query(Bracket).all():
        gp = {p.match_id: p.pick for p in b.group_picks}
        kp = {p.match_no: p.picked_team_id for p in b.knockout_picks}
        bd = score_bracket(gp, group_results, kp, knockout_results)

        row = b.score
        if row is None:
            row = BracketScore(bracket_id=b.id)
            db.add(row)
        row.group_points = bd["group_points"]
        row.knockout_points = bd["knockout_points"]
        row.champion_bonus = bd["champion_bonus"]
        row.total_points = bd["total_points"]
        row.recalculated_at = now
        scored.append((row, bd["total_points"]))

    # Standard competition ranking (ties share a rank; next rank skips).
    scored.sort(key=lambda x: x[1], reverse=True)
    last_pts: int | None = None
    last_rank = 0
    for i, (row, pts) in enumerate(scored, start=1):
        if pts != last_pts:
            last_rank = i
            last_pts = pts
        row.rank = last_rank

    db.commit()
    return len(scored)
