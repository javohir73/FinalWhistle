"""Tests for exact-version, pre-kickoff vNext shadow benchmarking."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Match, Prediction, Team, Tournament
from ml.evaluation.paired_challenger import PromotionPolicy
from pipeline.vnext_shadow import VNEXT_RECEIPT_KEY, champion_row_fingerprint
from pipeline.vnext_shadow_benchmark import benchmark_stored_vnext_shadow


CHAMPION = "poisson-elo-v0.5"
ARTIFACT_IDENTITY = "0123456789abcdef" * 4
CHALLENGER = f"fw-vnext-{ARTIFACT_IDENTITY[:31]}"
PREDICTOR_KIND = "frozen-pure-tempo-v1"
PAYLOAD_MODE = "calibrated_wdl"
# A genuinely different artifact that the 40-character tag cannot distinguish.
FORKED_IDENTITY = f"{ARTIFACT_IDENTITY[:-1]}0"


def _fixture(
    db,
    tournament: Tournament,
    index: int,
    *,
    final_score: tuple[int, int] = (2, 1),
    regulation_score: tuple[int, int] | None = None,
) -> Match:
    home = Team(name=f"Home {tournament.id}-{index}")
    away = Team(name=f"Away {tournament.id}-{index}")
    db.add_all([home, away])
    db.flush()
    kickoff = datetime(2026, 7, 1, 12, tzinfo=timezone.utc) + timedelta(days=index)
    match = Match(
        tournament_id=tournament.id,
        stage="group",
        team_home_id=home.id,
        team_away_id=away.id,
        kickoff_utc=kickoff,
        status="finished",
        score_home=final_score[0],
        score_away=final_score[1],
        score_home_90=regulation_score[0] if regulation_score else None,
        score_away_90=regulation_score[1] if regulation_score else None,
    )
    db.add(match)
    db.flush()
    return match


def _prediction(
    db,
    match: Match,
    version: str,
    probabilities: tuple[float, float, float],
    *,
    shadow: bool,
    created_at: datetime,
    reasons: list | None = None,
) -> Prediction:
    row = Prediction(
        match_id=match.id,
        model_version=version,
        created_at=created_at,
        is_shadow=shadow,
        prob_home_win=probabilities[0],
        prob_draw=probabilities[1],
        prob_away_win=probabilities[2],
        lambda_home=1.4 if not shadow else None,
        lambda_away=1.1 if not shadow else None,
        rho=0.0 if not shadow else None,
        reasons=[] if reasons is None else reasons,
        top_features=[],
    )
    db.add(row)
    db.flush()
    return row


def _linked_challenger(
    db,
    match: Match,
    champion: Prediction,
    probabilities: tuple[float, float, float],
    *,
    created_at: datetime,
    candidate_over_2_5: float = 0.55,
    artifact_identity: str = ARTIFACT_IDENTITY,
    predictor_kind: str = PREDICTOR_KIND,
    payload_mode: str = PAYLOAD_MODE,
) -> Prediction:
    cutoff = champion.created_at
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    receipt = {
        "artifact_identity": artifact_identity,
        "candidate_grid_sha256": "1" * 64,
        "candidate_max_goals": 10,
        "candidate_over_2_5": candidate_over_2_5,
        "champion_model_version": CHAMPION,
        "champion_payload_sha256": champion_row_fingerprint(champion),
        "features_as_of": cutoff.isoformat(),
        "payload_mode": payload_mode,
        "predictor_kind": predictor_kind,
        "schema_version": 2,
    }
    return _prediction(
        db,
        match,
        CHALLENGER,
        probabilities,
        shadow=True,
        created_at=created_at,
        reasons=[{VNEXT_RECEIPT_KEY: receipt}],
    )


def test_pairs_latest_exact_rows_before_kickoff_and_uses_regulation_score(db_session):
    tournament = Tournament(name="World Cup", year=2026)
    db_session.add(tournament)
    db_session.flush()
    paired = _fixture(
        db_session,
        tournament,
        0,
        final_score=(2, 1),
        regulation_score=(1, 1),
    )
    missing = _fixture(db_session, tournament, 1)
    before = paired.kickoff_utc - timedelta(hours=1)
    parent = _prediction(
        db_session,
        paired,
        CHAMPION,
        (0.1, 0.8, 0.1),
        shadow=False,
        created_at=before - timedelta(minutes=10),
    )
    _linked_challenger(
        db_session,
        paired,
        parent,
        (0.2, 0.7, 0.1),
        created_at=before - timedelta(minutes=5),
    )
    chosen = _linked_challenger(
        db_session,
        paired,
        parent,
        (0.05, 0.9, 0.05),
        created_at=before,
        candidate_over_2_5=0.2,
    )
    # A newer champion must not hijack the older challenger's content link.
    _prediction(
        db_session,
        paired,
        CHAMPION,
        (0.9, 0.01, 0.09),
        shadow=False,
        created_at=before + timedelta(minutes=10),
    )
    # This newer receipt-less row is invalid, so pairing falls back to `chosen`.
    _prediction(
        db_session,
        paired,
        CHALLENGER,
        (0.9, 0.05, 0.05),
        shadow=True,
        created_at=before + timedelta(minutes=20),
    )
    # These tempting rows must never enter the pair.
    _prediction(
        db_session,
        paired,
        CHALLENGER,
        (0.9, 0.05, 0.05),
        shadow=True,
        created_at=paired.kickoff_utc,
    )
    _prediction(
        db_session,
        paired,
        f"{CHALLENGER[:-1]}x",
        (0.9, 0.05, 0.05),
        shadow=True,
        created_at=before,
    )
    _prediction(
        db_session,
        missing,
        CHAMPION,
        (0.7, 0.2, 0.1),
        shadow=False,
        created_at=missing.kickoff_utc - timedelta(hours=1),
    )
    db_session.commit()
    row_count = db_session.query(Prediction).count()

    report = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
        n_bootstrap=200,
    )

    assert report["eligible_matches"] == 2
    assert report["paired_matches"] == 1
    assert report["paired_match_ids"] == [paired.id]
    assert report["paired_prediction_ids"] == [{
        "match_id": paired.id,
        "champion_prediction_id": parent.id,
        "challenger_prediction_id": chosen.id,
    }]
    assert report["invalid_or_unlinked_challenger_rows"] == 1
    assert report["coverage"] == 0.5
    assert report["benchmark"]["champion"]["log_loss"] == pytest.approx(-math.log(0.8))
    assert report["benchmark"]["challenger"]["log_loss"] == pytest.approx(-math.log(0.9))
    assert report["benchmark"]["n_clusters"] == 1
    assert report["goal_market_benchmark"]["n_matches"] == 1
    assert report["goal_market_paired_match_ids"] == [paired.id]
    assert report["promotion"]["promote"] is False
    assert report["wdl_guardrail"]["passes_superiority_gate"] is False
    assert "automatic promotion is disabled; this command is evidence-only" in report[
        "promotion"
    ]["reasons"]
    assert db_session.query(Prediction).count() == row_count


def test_same_tag_prefix_with_a_different_full_identity_is_not_paired(db_session):
    tournament = Tournament(name="Fork Cup", year=2026)
    db_session.add(tournament)
    db_session.flush()
    match = _fixture(db_session, tournament, 0)
    before = match.kickoff_utc - timedelta(hours=1)
    parent = _prediction(
        db_session,
        match,
        CHAMPION,
        (0.5, 0.3, 0.2),
        shadow=False,
        created_at=before,
    )
    _linked_challenger(
        db_session,
        match,
        parent,
        (0.6, 0.3, 0.1),
        created_at=before + timedelta(minutes=1),
        artifact_identity=FORKED_IDENTITY,
    )
    db_session.commit()

    report = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
        artifact_identity=ARTIFACT_IDENTITY,
        predictor_kind=PREDICTOR_KIND,
        payload_mode=PAYLOAD_MODE,
    )

    assert CHALLENGER == f"fw-vnext-{FORKED_IDENTITY[:31]}"
    assert report["eligible_matches"] == 1
    assert report["paired_matches"] == 0
    assert report["invalid_or_unlinked_challenger_rows"] == 1
    assert report["challenger_artifact"]["artifact_identity"] == ARTIFACT_IDENTITY


@pytest.mark.parametrize(
    "divergent",
    [
        {"artifact_identity": FORKED_IDENTITY},
        {"predictor_kind": "frozen-pure-tempo-v2"},
        {"payload_mode": "parity"},
    ],
)
def test_first_accepted_receipt_pins_the_artifact_the_report_scores(
    db_session, divergent
):
    tournament = Tournament(name="Pin Cup", year=2026)
    db_session.add(tournament)
    db_session.flush()
    scored = _fixture(db_session, tournament, 0)
    forked = _fixture(db_session, tournament, 1)
    for match, overrides in ((scored, {}), (forked, divergent)):
        before = match.kickoff_utc - timedelta(hours=1)
        parent = _prediction(
            db_session,
            match,
            CHAMPION,
            (0.5, 0.3, 0.2),
            shadow=False,
            created_at=before,
        )
        _linked_challenger(
            db_session,
            match,
            parent,
            (0.6, 0.3, 0.1),
            created_at=before + timedelta(minutes=1),
            **overrides,
        )
    db_session.commit()

    report = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
        n_bootstrap=200,
    )

    assert report["eligible_matches"] == 2
    assert report["paired_matches"] == 1
    assert report["paired_match_ids"] == [scored.id]
    assert report["invalid_or_unlinked_challenger_rows"] == 1
    assert report["challenger_artifact"] == {
        "artifact_identity": ARTIFACT_IDENTITY,
        "predictor_kind": PREDICTOR_KIND,
        "payload_mode": PAYLOAD_MODE,
    }


def test_wrong_shadow_flags_and_post_kickoff_champion_are_ineligible(db_session):
    tournament = Tournament(name="Cup", year=2026)
    db_session.add(tournament)
    db_session.flush()
    match = _fixture(db_session, tournament, 0)
    _prediction(
        db_session,
        match,
        CHAMPION,
        (0.7, 0.2, 0.1),
        shadow=True,
        created_at=match.kickoff_utc - timedelta(hours=1),
    )
    _prediction(
        db_session,
        match,
        CHAMPION,
        (0.7, 0.2, 0.1),
        shadow=False,
        created_at=match.kickoff_utc + timedelta(seconds=1),
    )
    _prediction(
        db_session,
        match,
        CHALLENGER,
        (0.8, 0.1, 0.1),
        shadow=False,
        created_at=match.kickoff_utc - timedelta(hours=1),
    )
    db_session.commit()

    report = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
    )
    assert report["eligible_matches"] == 0
    assert report["paired_matches"] == 0
    assert report["benchmark"] is None
    assert report["promotion"]["promote"] is False


def test_knockout_without_regulation_score_is_excluded_not_final_score_labeled(
    db_session,
):
    tournament = Tournament(name="Knockout Cup", year=2026)
    db_session.add(tournament)
    db_session.flush()
    match = _fixture(db_session, tournament, 0, final_score=(2, 1))
    match.stage = "QF"
    at = match.kickoff_utc - timedelta(hours=1)
    _prediction(db_session, match, CHAMPION, (0.2, 0.6, 0.2), shadow=False, created_at=at)
    _prediction(db_session, match, CHALLENGER, (0.1, 0.8, 0.1), shadow=True, created_at=at)
    db_session.commit()

    report = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
    )
    assert report["total_finished_matches"] == 1
    assert report["excluded_missing_regulation_score"] == 1
    assert report["eligible_matches"] == 0
    assert report["paired_matches"] == 0


def test_tournament_scope_and_clusters_are_explicit(db_session):
    tournaments = [Tournament(name=f"Cup {i}", year=2020 + i) for i in range(2)]
    db_session.add_all(tournaments)
    db_session.flush()
    for index, tournament in enumerate(tournaments):
        match = _fixture(db_session, tournament, index)
        at = match.kickoff_utc - timedelta(hours=1)
        champion = _prediction(
            db_session,
            match,
            CHAMPION,
            (0.6, 0.2, 0.2),
            shadow=False,
            created_at=at,
        )
        _linked_challenger(
            db_session,
            match,
            champion,
            (0.7, 0.2, 0.1),
            created_at=at + timedelta(minutes=1),
        )
    db_session.commit()

    all_report = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
        policy=PromotionPolicy(min_matches=1, min_clusters=1),
        n_bootstrap=200,
    )
    scoped = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
        tournament_id=tournaments[0].id,
        n_bootstrap=200,
    )
    assert all_report["benchmark"]["n_clusters"] == 2
    assert all_report["paired_matches"] == 2
    assert scoped["scope"] == {"tournament_id": tournaments[0].id}
    assert scoped["paired_matches"] == 1


def test_passing_superiority_gate_is_not_a_second_promotion_authorization(db_session):
    tournament = Tournament(name="Superior Cup", year=2026)
    db_session.add(tournament)
    db_session.flush()
    for index in range(2):
        match = _fixture(db_session, tournament, index, final_score=(2, 1))
        before = match.kickoff_utc - timedelta(hours=1)
        parent = _prediction(
            db_session,
            match,
            CHAMPION,
            (0.2, 0.6, 0.2),
            shadow=False,
            created_at=before,
        )
        _linked_challenger(
            db_session,
            match,
            parent,
            (0.8, 0.1, 0.1),
            created_at=before + timedelta(minutes=1),
        )
    db_session.commit()

    report = benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
        policy=PromotionPolicy(min_matches=1, min_clusters=1, min_coverage=0.5),
        n_bootstrap=200,
    )

    assert report["paired_matches"] == 2
    assert report["wdl_guardrail"]["passes_superiority_gate"] is True
    assert "promote" not in report["wdl_guardrail"]
    assert report["promotion"]["promote"] is False


@pytest.mark.parametrize("champion,challenger", [("same", "same"), ("", "other")])
def test_rejects_ambiguous_versions(db_session, champion, challenger):
    with pytest.raises(ValueError):
        benchmark_stored_vnext_shadow(
            db_session,
            champion_version=champion,
            challenger_tag=challenger,
        )


def test_read_only_benchmark_does_not_autoflush_unrelated_pending_state(db_session):
    pending = Team(name="Pending and unrelated")
    db_session.add(pending)

    benchmark_stored_vnext_shadow(
        db_session,
        champion_version=CHAMPION,
        challenger_tag=CHALLENGER,
    )

    assert pending.id is None
    assert pending in db_session.new
