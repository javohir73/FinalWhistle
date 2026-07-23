"""Tests for the user-tips grading pass (Beat-the-AI loop, Slice 2).

Builds tiny sport_matches/sport_teams + tip_players/user_tips fixtures
directly via db_session (conftest.py's SQLite fixture) -- same style as
nrl_predict_test.py: grade() is exercised directly, not through the API.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import SportMatch, SportTeam, TipPlayer, UserTip
from pipeline.sports.nrl_user_tips import grade

SPORT = "nrl"


def _team(db, name):
    t = SportTeam(sport=SPORT, name=name)
    db.add(t)
    db.flush()
    return t


def _match(db, home, away, season, round_, match_no, kickoff,
           status="finished", score_home=20, score_away=16):
    m = SportMatch(
        sport=SPORT, season=season, round=round_, match_no=match_no,
        kickoff_utc=kickoff, home_team_id=home.id, away_team_id=away.id,
        score_home=score_home, score_away=score_away, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _player(db, device_id="3fa85f64-5717-4562-b3fc-2c963f66afa6", handle="TestTipper"):
    p = TipPlayer(device_id=device_id, handle=handle)
    db.add(p)
    db.flush()
    return p


def _tip(db, match, player, pick, margin=None, updated_at=None):
    t = UserTip(match_id=match.id, player_id=player.id, pick=pick, margin=margin,
                updated_at=updated_at or (match.kickoff_utc - timedelta(hours=1)))
    db.add(t)
    db.flush()
    return t


def _kickoff(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _two_match_round(db, season=2026, round_=3):
    """A round with 2 finished matches: earliest kickoff (the featured match,
    Storm beat Eels by 10) and a later one (Titans beat Broncos by 4)."""
    storm, eels = _team(db, "Storm"), _team(db, "Eels")
    broncos, titans = _team(db, "Broncos"), _team(db, "Titans")
    featured = _match(db, storm, eels, season, round_, 1, _kickoff(2026, 8, 1),
                       score_home=20, score_away=10)
    other = _match(db, broncos, titans, season, round_, 2, _kickoff(2026, 8, 2),
                   score_home=14, score_away=18)
    return featured, other


# ---- points: correct/wrong/draw, non-featured ----

def test_grade_correct_non_featured_pick_awards_one_point(db_session):
    _, other = _two_match_round(db_session)
    player = _player(db_session)
    tip = _tip(db_session, other, player, "away")  # Titans won 18-14
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 1
    assert tip.round_margin is None
    assert tip.graded_at is not None


def test_grade_wrong_non_featured_pick_awards_zero_points(db_session):
    _, other = _two_match_round(db_session)
    player = _player(db_session)
    tip = _tip(db_session, other, player, "home")  # wrong -- away won
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 0
    assert tip.round_margin is None


def test_grade_draw_awards_point_regardless_of_pick(db_session):
    storm, eels = _team(db_session, "Storm"), _team(db_session, "Eels")
    m = _match(db_session, storm, eels, 2026, 4, 1, _kickoff(2026, 8, 8),
               score_home=18, score_away=18)
    player = _player(db_session)
    tip = _tip(db_session, m, player, "home")  # picked home; actual is a draw
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 1  # comp-standard rule: a draw scores every tipper


# ---- featured-match margin tiebreak ----

def test_grade_featured_correct_pick_margin_tiebreak(db_session):
    featured, _ = _two_match_round(db_session)  # Storm won by 10
    player = _player(db_session)
    tip = _tip(db_session, featured, player, "home", margin=7)
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 1
    assert tip.round_margin == abs(10 - 7)


def test_grade_featured_wrong_pick_margin_penalty(db_session):
    featured, _ = _two_match_round(db_session)  # actual margin 10, home won
    player = _player(db_session)
    tip = _tip(db_session, featured, player, "away", margin=7)  # wrong side
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 0
    assert tip.round_margin == 10 + 7


def test_grade_non_featured_never_gets_round_margin_even_if_margin_set(db_session):
    """The submit API only ever accepts a margin on the featured match, but
    grade() itself is what enforces round_margin staying None off it --
    belt-and-braces if a margin somehow landed on the wrong row."""
    _, other = _two_match_round(db_session)
    player = _player(db_session)
    tip = _tip(db_session, other, player, "away", margin=4)
    db_session.commit()

    grade(db_session)

    db_session.refresh(tip)
    assert tip.points == 1
    assert tip.round_margin is None


# ---- idempotency ----

def test_grade_is_idempotent_on_rerun(db_session):
    featured, other = _two_match_round(db_session)
    player = _player(db_session)
    t1 = _tip(db_session, featured, player, "home", margin=8)
    t2 = _tip(db_session, other, player, "away")
    db_session.commit()

    first = grade(db_session)
    second = grade(db_session)

    assert first == 2
    assert second == 0
    db_session.refresh(t1)
    db_session.refresh(t2)
    assert t1.points == 1 and t1.round_margin == 2
    assert t2.points == 1


def test_grade_recomputes_when_match_result_changes(db_session):
    """Unlike nrl_predict.grade()'s once-only guard (an existing
    SportPredictionResult blocks a match forever), a corrected score on an
    already-graded match must flip the stored points/round_margin -- grade()
    always recomputes from the current score, so a rare correction lands."""
    featured, _ = _two_match_round(db_session)  # Storm 20-10 Eels
    player = _player(db_session)
    tip = _tip(db_session, featured, player, "home", margin=10)  # exact guess
    db_session.commit()

    grade(db_session)
    db_session.refresh(tip)
    assert tip.points == 1
    assert tip.round_margin == 0
    first_graded_at = tip.graded_at

    # Score correction flips the result to an away win.
    featured.score_home, featured.score_away = 10, 20
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 0
    assert tip.round_margin == 10 + 10  # actual_margin(10) + guess(10), now the wrong side
    assert tip.graded_at >= first_graded_at


def test_grade_recomputes_when_match_result_changes_past_kickoff(db_session):
    """Regression: UserTip.updated_at must track ONLY submit_tip's own pick
    writes, never a grading write (see models.UserTip -- no more
    onupdate=func.now()). test_grade_recomputes_when_match_result_changes
    covers the same "a correction must flip the stored result" behavior but
    with a future-dated fixture kickoff, which never exercised the bug: the
    ORM's onupdate used to bump updated_at to grade-time on the FIRST grade()
    write, and with a past kickoff that pushed updated_at past kickoff_utc --
    so every later grade() run wrongly excluded the tip via the
    belt-and-braces filter above, and a correction could never land."""
    storm, eels = _team(db_session, "Storm"), _team(db_session, "Eels")
    kickoff = datetime.now(timezone.utc) - timedelta(days=2)
    m = _match(db_session, storm, eels, 2026, 9, 1, kickoff, score_home=20, score_away=10)
    player = _player(db_session)
    tip = _tip(db_session, m, player, "home", margin=10, updated_at=kickoff - timedelta(hours=1))
    db_session.commit()

    grade(db_session)
    db_session.refresh(tip)
    assert tip.points == 1
    assert tip.round_margin == 0

    # Score correction flips the result to an away win.
    m.score_home, m.score_away = 10, 20
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 0
    assert tip.round_margin == 10 + 10  # actual_margin(10) + guess(10), now the wrong side


# ---- is_featured is a snapshot, not recomputed live (reschedule safety) ----

def test_grade_prefers_pinned_is_featured_over_current_reschedule(db_session):
    """A margin legitimately entered on the round's featured match at submit
    time must still score even if the round is later reshuffled so a
    DIFFERENT match becomes the earliest kickoff -- UserTip.is_featured pins
    the snapshot submit_tip took, so grade() doesn't silently drop the
    margin by recomputing "featured" from the round's current order."""
    storm, eels = _team(db_session, "Storm"), _team(db_session, "Eels")
    broncos, titans = _team(db_session, "Broncos"), _team(db_session, "Titans")
    # A was earliest at submit time (hence its tip was pinned featured); a
    # reschedule since then made B the earliest kickoff in the round.
    a = _match(db_session, storm, eels, 2026, 10, 1, _kickoff(2026, 8, 20),
               score_home=20, score_away=10)
    _match(db_session, broncos, titans, 2026, 10, 2, _kickoff(2026, 8, 19),
           score_home=14, score_away=18)
    player = _player(db_session)
    tip = _tip(db_session, a, player, "home", margin=8)
    tip.is_featured = True
    db_session.commit()

    n = grade(db_session)

    assert n == 1
    db_session.refresh(tip)
    assert tip.points == 1
    assert tip.round_margin == abs(10 - 8)  # margin honored despite B now being earliest


def test_grade_falls_back_to_live_featured_check_when_pin_is_null(db_session):
    """Rows written before is_featured existed (or built directly, as every
    other test here does) carry NULL -- grade() must fall back to the live
    earliest-kickoff computation for those, unchanged from before the pin."""
    featured, other = _two_match_round(db_session)
    player = _player(db_session)
    tip = _tip(db_session, featured, player, "home", margin=7)
    assert tip.is_featured is None
    db_session.commit()

    grade(db_session)

    db_session.refresh(tip)
    assert tip.round_margin == abs(10 - 7)


# ---- belt-and-braces: post-kickoff tip is excluded, not scored zero ----

def test_grade_excludes_tip_submitted_after_kickoff(db_session):
    """Shouldn't exist given the submit API's kickoff lock, but a stray
    updated_at > kickoff_utc row must never be scored -- left permanently
    ungraded rather than scored zero."""
    storm, eels = _team(db_session, "Storm"), _team(db_session, "Eels")
    m = _match(db_session, storm, eels, 2026, 5, 1, _kickoff(2026, 8, 15),
               score_home=20, score_away=10)
    player = _player(db_session)
    late = _tip(db_session, m, player, "home",
                updated_at=m.kickoff_utc + timedelta(hours=1))
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    db_session.refresh(late)
    assert late.points is None
    assert late.round_margin is None
    assert late.graded_at is None

    n2 = grade(db_session)  # re-running never picks it up either
    assert n2 == 0


def test_grade_excludes_tip_on_match_with_no_kickoff_recorded(db_session):
    """Belt-and-braces: not reachable via today's NRL feed (every real match
    has a kickoff_utc), but a finished match missing one has nothing to check
    a tip's updated_at against, so it must be excluded rather than graded
    on trust."""
    storm, eels = _team(db_session, "Storm"), _team(db_session, "Eels")
    m = SportMatch(sport=SPORT, season=2026, round=8, match_no=1, kickoff_utc=None,
                   home_team_id=storm.id, away_team_id=eels.id,
                   score_home=20, score_away=10, status="finished")
    db_session.add(m)
    db_session.flush()
    player = _player(db_session)
    tip = _tip(db_session, m, player, "home", updated_at=datetime.now(timezone.utc))
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    db_session.refresh(tip)
    assert tip.points is None
    assert tip.graded_at is None


# ---- no-ops ----

def test_grade_no_tips_is_a_noop(db_session):
    storm, eels = _team(db_session, "Storm"), _team(db_session, "Eels")
    _match(db_session, storm, eels, 2026, 6, 1, _kickoff(2026, 8, 22),
           score_home=20, score_away=10)
    db_session.commit()

    n = grade(db_session)

    assert n == 0


def test_grade_skips_scheduled_match_even_with_tips(db_session):
    storm, eels = _team(db_session, "Storm"), _team(db_session, "Eels")
    m = _match(db_session, storm, eels, 2026, 7, 1, _kickoff(2026, 8, 29),
               status="scheduled", score_home=None, score_away=None)
    player = _player(db_session)
    tip = _tip(db_session, m, player, "home",
               updated_at=m.kickoff_utc - timedelta(hours=1))
    db_session.commit()

    n = grade(db_session)

    assert n == 0
    db_session.refresh(tip)
    assert tip.points is None
    assert tip.graded_at is None
