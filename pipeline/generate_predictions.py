"""Generate predictions for all upcoming WC2026 matches (PRD §4.2, §17).

For each scheduled group match it builds features, runs the Poisson engine,
derives confidence + reasons, and writes a Prediction row plus a §17-shaped
payload. It then simulates each group to fill predicted standings + qualification
probabilities. Designed to be called by the daily pipeline (task 7).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Group, GroupTeam, HistoricalMatch, Match, Odds, Prediction, Standing, Team, TournamentOdds
from ml.evaluation.calibration import calibrate, effective_gap
from ml.explain.reasons import confidence_level, generate_reasons, top_features
from ml.features.build_features import build_match_features, estimate_strength
from ml.features.wdl_features import assemble_features, window_stats
from ml.models.odds_blend import blend_lambda_total, market_lambda_total
from ml.models.params import ModelParams, load_params
from ml.models.poisson import predict_from_lambdas, predict_match
from ml.models.poisson import predict_match
from ml.models.team_offsets import load_team_offsets, offsets_for
from ml.ratings.elo import HOME_ADVANTAGE
from ml.simulate.bracket import GroupFixture as KnockoutFixture, simulate_tournament
from ml.simulate.group_sim import GroupFixture, simulate_group

#: Version tag for shadow rows (exact-score program FR-4.4): the odds-anchored
#: twin of every production prediction. Never served, never in the public
#: record — promotion to the headline is a manual owner decision (FR-4.8).
SHADOW_MODEL_VERSION = "poisson-elo-v0.3-shadow"


def _host_adv(match: Match, home: Team, home_advantage: float = HOME_ADVANTAGE) -> float:
    """Signed host bonus: + if home is host, - if away is host (boosts away)."""
    if match.host_team_id is None:
        return 0.0
    return home_advantage if match.host_team_id == home.id else -home_advantage


def _offsets_by_team_id(params: ModelParams, teams: list[Team]) -> dict[int, tuple[float, float]] | None:
    """{team_id: (atk, def)} from the enabled offsets store, or None when the
    flag is off (the shipped default). The ONE loader for the match cards AND
    both Monte-Carlo simulations, so a flipped team_offsets flag can never serve
    per-match probabilities and qualification/title odds from divergent lambdas
    (FR-5.3)."""
    if not params.team_offsets:
        return None
    store = load_team_offsets(params.team_offsets.get("file"))
    return {t.id: offsets_for(store, t.name) for t in teams}


def _recent_appearances(db: Session, team_id: int, limit: int = 10) -> list[tuple[int, int]]:
    """A team's most-recent (goals_for, goals_against) from played history."""
    rows = (
        db.query(HistoricalMatch)
        .filter(
            (HistoricalMatch.team_a_id == team_id) | (HistoricalMatch.team_b_id == team_id),
            HistoricalMatch.score_a.isnot(None), HistoricalMatch.score_b.isnot(None),
        )
        .order_by(HistoricalMatch.date.desc())
        .limit(limit)
        .all()
    )
    out: list[tuple[int, int]] = []
    for m in rows:
        if m.team_a_id == team_id:
            out.append((m.score_a, m.score_b))
        else:
            out.append((m.score_b, m.score_a))
    return out


def _boost_features(db: Session, home: Team, away: Team,
                    elo_home: float, elo_away: float, is_neutral: bool,
                    h2h: dict) -> dict:
    """Assemble the booster's feature dict for an upcoming match — same schema and
    reducer as training (leak-free: all of history precedes a scheduled fixture).
    `h2h` is reused from the caller's build_match_features (home perspective:
    a_wins/matches) to avoid a duplicate head-to-head query."""
    form_h, gf_h, ga_h, n_h = window_stats(_recent_appearances(db, home.id))
    form_a, gf_a, ga_a, n_a = window_stats(_recent_appearances(db, away.id))
    return assemble_features(
        elo_home=elo_home, elo_away=elo_away, is_neutral=is_neutral,
        form_home=form_h, form_away=form_a,
        gf_avg_home=gf_h, gf_avg_away=gf_a, ga_avg_home=ga_h, ga_avg_away=ga_a,
        h2h_home_wins=h2h["a_wins"], h2h_matches=h2h["matches"],
        data_points_home=n_h, data_points_away=n_a,
    )


def build_payload(
    db: Session, match: Match, model_version: str,
    strengths: dict[int, float] | None = None,
    params: ModelParams | None = None,
    booster: "WdlBoost | None" = None,
) -> dict | None:
    """Build the PRD §17 prediction payload for a match (None if teams unknown).

    ``strengths`` (team_id -> effective Elo) lets the learning loop inject
    tournament-adjusted ratings; absent entries fall back to the base rating.
    ``params`` are the tuned engine parameters (base/beta/rho/temperature/
    home_adv); they default to the loaded model_params.json or the v0.1 constants.
    """
    if match.team_home_id is None or match.team_away_id is None:
        return None
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)

    params = params or load_params()
    feats = build_match_features(db, home, away, host_team_id=match.host_team_id)
    host_adv = _host_adv(match, home, params.home_adv)
    strengths = strengths or {}
    elo_home = strengths.get(home.id, estimate_strength(home)[0])
    elo_away = strengths.get(away.id, estimate_strength(away)[0])
    # Keep the explanation layer consistent with the probabilities: reasons and
    # top_features must describe the SAME effective ratings the model used,
    # not the pre-tournament base.
    feats.elo_home = elo_home
    feats.elo_away = elo_away
    feats.elo_diff = elo_home - elo_away
    # Per-team attack/defence offsets (FR-5.3): opt-in via model_params.json
    # ("team_offsets": null keeps this a strict no-op — bit-identical lambdas).
    # Loaded through the same helper the group/tournament sims use, so the card
    # and the simulations always agree on a team's offsets.
    offs = _offsets_by_team_id(params, [home, away]) or {}
    atk_h, def_h = offs.get(home.id, (0.0, 0.0))
    atk_a, def_a = offs.get(away.id, (0.0, 0.0))
    pred = predict_match(
        elo_home, elo_away, home_adv=host_adv,
        base=params.base, beta=params.beta, rho=params.rho,
        temperature=params.temperature, calibrator=params.calibrator,
        atk_home=atk_h, def_home=def_h, atk_away=atk_a, def_away=def_a,
    )

    # Poisson W/D/L is the base. If a booster blend is shipped (and a trained
    # booster is supplied), blend toward it and re-calibrate. The SCORELINE stays
    # Poisson's — the booster only refines the W/D/L triple (spec §1).
    # NOTE: the argmax of the blended triple may disagree with the Poisson scoreline
    # (e.g. bars lean draw while the score reads 1-0). That is intentional per the
    # design boundary; the predicted score is a separate Poisson-derived signal.
    p_home, p_draw, p_away = pred.prob_home_win, pred.prob_draw, pred.prob_away_win
    if params.wdl_blend and booster is not None:
        from ml.models.wdl_boost import blend_triples  # deferred: keeps sklearn off the blend-off path

        feats_v = _boost_features(db, home, away, elo_home, elo_away, match.is_neutral, feats.h2h)
        b = booster.predict_proba(feats_v)
        p_home, p_draw, p_away = blend_triples(
            (p_home, p_draw, p_away), (b["H"], b["D"], b["A"]), params.wdl_blend["weight"]
        )
        p_home, p_draw, p_away = calibrate(
            (p_home, p_draw, p_away), params.wdl_blend.get("calibrator")
        )

    cold_start = feats.strength_source_home != "elo" or feats.strength_source_away != "elo"
    confidence = confidence_level(
        p_home, p_draw, p_away,
        feats.data_points_home, feats.data_points_away, cold_start,
    )
    reasons = generate_reasons(
        feats, home.name, away.name,
        p_home, p_draw, p_away,
    )
    factors = top_features(feats)

    return {
        "match_id": match.id,
        "model_version": model_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "teams": {"home": home.name, "away": away.name},
        "is_neutral": match.is_neutral,
        "probabilities": {
            "home_win": round(p_home, 4),
            "draw": round(p_draw, 4),
            "away_win": round(p_away, 4),
        },
        "predicted_score": {
            "home": pred.score_home,
            "away": pred.score_away,
            "probability": round(pred.score_prob, 4),
        },
        "lambda_home": round(pred.lambda_home, 4),
        "lambda_away": round(pred.lambda_away, 4),
        "rho": params.rho,
        "confidence": confidence,
        "reasons": reasons,
        "top_features": factors,
        "head_to_head": {
            "matches": feats.h2h["matches"],
            "home_wins": feats.h2h["a_wins"],
            "draws": feats.h2h["draws"],
            "away_wins": feats.h2h["b_wins"],
        },
        "odds_comparison": {"available": False},
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


def _write_prediction(db: Session, payload: dict, model_version: str,
                      is_shadow: bool = False) -> None:
    p = payload["probabilities"]
    s = payload["predicted_score"]
    db.add(
        Prediction(
            match_id=payload["match_id"],
            model_version=model_version,
            prob_home_win=p["home_win"],
            prob_draw=p["draw"],
            prob_away_win=p["away_win"],
            predicted_score_home=s["home"],
            predicted_score_away=s["away"],
            predicted_score_prob=s["probability"],
            lambda_home=payload.get("lambda_home"),
            lambda_away=payload.get("lambda_away"),
            rho=payload.get("rho"),
            confidence=payload["confidence"],
            reasons=payload["reasons"],
            top_features=payload["top_features"],
            is_shadow=is_shadow,
        )
    )


def _latest_odds(db: Session, match_id: int) -> Odds | None:
    """Freshest stored bookmaker consensus for a match (None when unpriced)."""
    return (
        db.query(Odds)
        .filter(Odds.match_id == match_id)
        .order_by(Odds.captured_at.desc(), Odds.id.desc())
        .first()
    )


def write_shadow_prediction(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
) -> None:
    """Write the shadow twin of a just-built production payload (FR-4.4).

    With a stored market total AND ``params.w_odds`` > 0, the twin's lambda
    SUM is anchored toward the market (Elo split preserved, FR-4.3) and the
    grid/triple/headline are recomputed through the same calibrated pipeline
    (``predict_from_lambdas``). Otherwise the twin copies the production
    numbers exactly, so the production-vs-shadow comparison is a clean null
    test until odds exist and a weight is deliberately set. Explanation
    fields (confidence/reasons/top_features) always mirror production — the
    twin is internal-only and never rendered. NOTE: the anchored triple is
    pure Poisson (no W/D/L booster leg even if wdl_blend ever ships) so the
    comparison attributes divergence to the odds anchor alone.

    The ``w_odds`` gate runs FIRST: with the shipped 0.0 the blend is the
    identity, so the odds lookup and the market inversion (whose 1X2 fallback
    is a costly double bisection) are skipped entirely — this path executes
    synchronously inside latency-sensitive request chains.
    """
    shadow = payload
    if params.w_odds <= 0.0:
        _write_prediction(db, shadow, SHADOW_MODEL_VERSION, is_shadow=True)
        return
    odds = _latest_odds(db, match.id)
    market_total = None
    if odds is not None:
        market_total = market_lambda_total(
            odds_over25=odds.odds_over25, odds_under25=odds.odds_under25,
            odds_home=odds.odds_home, odds_draw=odds.odds_draw, odds_away=odds.odds_away,
        )
    if market_total is not None:
        lam_h, lam_a = blend_lambda_total(
            payload["lambda_home"], payload["lambda_away"], market_total, params.w_odds
        )
        home = db.get(Team, match.team_home_id)
        away = db.get(Team, match.team_away_id)
        elo_home = strengths.get(home.id, estimate_strength(home)[0])
        elo_away = strengths.get(away.id, estimate_strength(away)[0])
        pred = predict_from_lambdas(
            lam_h, lam_a, rho=params.rho, temperature=params.temperature,
            calibrator=params.calibrator,
            eff_gap=effective_gap(elo_home, elo_away, _host_adv(match, home, params.home_adv)),
        )
        shadow = {
            **payload,
            "probabilities": {
                "home_win": round(pred.prob_home_win, 4),
                "draw": round(pred.prob_draw, 4),
                "away_win": round(pred.prob_away_win, 4),
            },
            "predicted_score": {
                "home": pred.score_home,
                "away": pred.score_away,
                "probability": round(pred.score_prob, 4),
            },
            "lambda_home": round(pred.lambda_home, 4),
            "lambda_away": round(pred.lambda_away, 4),
        }
    _write_prediction(db, shadow, SHADOW_MODEL_VERSION, is_shadow=True)


def _played_score(m: Match) -> tuple[int, int] | None:
    """The final score when a match has actually been played, else None.
    In-play matches stay None — they aren't final until the whistle."""
    if m.status == "finished" and m.score_home is not None and m.score_away is not None:
        return (m.score_home, m.score_away)
    return None


def _simulate_standings(
    db: Session, group: Group, model_version: str, n_sims: int,
    strengths: dict[int, float] | None = None,
    params: ModelParams | None = None,
) -> None:
    params = params or load_params()
    members = [gt.team for gt in group.group_teams]
    strengths = strengths or {}
    team_elos = {t.id: strengths.get(t.id, estimate_strength(t)[0]) for t in members}
    fixtures = []
    for m in db.query(Match).filter_by(group_id=group.id).all():
        if m.team_home_id and m.team_away_id:
            home = db.get(Team, m.team_home_id)
            fixtures.append(
                GroupFixture(m.team_home_id, m.team_away_id,
                             home_adv=_host_adv(m, home, params.home_adv),
                             score=_played_score(m))
            )

    results = simulate_group(
        team_elos, fixtures, n_sims=n_sims, seed=2026,
        base=params.base, beta=params.beta, rho=params.rho,
        team_offsets=_offsets_by_team_id(params, members),
    )
    # Persist REAL tallies (finished matches only) — the table users see is the
    # actual league table; only qualification_prob comes from the simulation.
    from app.serializers import live_group_table

    real = live_group_table(db, group.id, include_in_play=False)
    now = datetime.now(timezone.utc)
    for team_id, r in results.items():
        row = db.query(Standing).filter_by(group_id=group.id, team_id=team_id).one_or_none()
        if row is None:
            row = Standing(group_id=group.id, team_id=team_id)
            db.add(row)
        t = real.get(team_id, {"played": 0, "won": 0, "drawn": 0, "lost": 0,
                               "points": 0, "gf": 0, "ga": 0})
        row.qualification_prob = r["qualification_prob"]
        row.played = t["played"]
        row.won = t["won"]
        row.drawn = t["drawn"]
        row.lost = t["lost"]
        row.points = t["points"]
        row.goals_for = t["gf"]
        row.goals_against = t["ga"]
        row.goal_diff = t["gf"] - t["ga"]
        row.as_of = now


def _simulate_tournament(
    db: Session, n_sims: int, strengths: dict[int, float] | None = None,
    params: ModelParams | None = None,
) -> int:
    """Run the full group→knockout Monte-Carlo and persist per-team round/title
    probabilities. Returns the number of teams with odds written."""
    params = params or load_params()
    groups: dict[str, list[int]] = {}
    fixtures: dict[str, list[KnockoutFixture]] = {}
    team_elos: dict[int, float] = {}
    strengths = strengths or {}
    all_members: list[Team] = []

    for group in db.query(Group).all():
        letter = group.name.split()[-1]  # "Group A" -> "A"
        members = [gt.team for gt in group.group_teams]
        all_members.extend(members)
        groups[letter] = [t.id for t in members]
        for t in members:
            team_elos[t.id] = strengths.get(t.id, estimate_strength(t)[0])
        fx: list[KnockoutFixture] = []
        for m in db.query(Match).filter_by(group_id=group.id).all():
            if m.team_home_id and m.team_away_id:
                home = db.get(Team, m.team_home_id)
                fx.append(KnockoutFixture(m.team_home_id, m.team_away_id,
                                          _host_adv(m, home, params.home_adv),
                                          score=_played_score(m)))
        fixtures[letter] = fx

    # Need the full 12-group structure to run the bracket; skip cleanly otherwise.
    if len(groups) < 12:
        return 0

    hosts = {t.name: t.id for t in db.query(Team).filter_by(is_host=True).all()}
    country_to_team = {"United States": hosts.get("United States"),
                       "Mexico": hosts.get("Mexico"),
                       "Canada": hosts.get("Canada")}
    ko_host_by_match: dict[int, int] = {}
    for m in db.query(Match).filter(Match.group_id.is_(None), Match.venue_country.isnot(None)).all():
        team_id = country_to_team.get(m.venue_country)
        if team_id is not None:
            ko_host_by_match[m.id] = team_id

    # Already-played knockout ties are facts: pin them so a finished match forces
    # its winner forward and its loser out in every draw (analogous to a played
    # group fixture's score). Keyed by official match number.
    from app.scoring import knockout_played_from_db

    ko_results = knockout_played_from_db(db)

    results = simulate_tournament(
        team_elos, groups, fixtures, n_sims=n_sims, seed=2026,
        base=params.base, beta=params.beta, rho=params.rho,
        pk_beta=params.pk_beta, home_adv=params.home_adv,
        ko_host_by_match=ko_host_by_match, ko_results=ko_results,
        team_offsets=_offsets_by_team_id(params, all_members),
    )
    now = datetime.now(timezone.utc)
    for team_id, r in results.items():
        row = db.query(TournamentOdds).filter_by(team_id=team_id).one_or_none()
        if row is None:
            row = TournamentOdds(team_id=team_id)
            db.add(row)
        row.make_knockout = r["make_knockout"]
        row.reach_r16 = r["reach_r16"]
        row.reach_qf = r["reach_qf"]
        row.reach_sf = r["reach_sf"]
        row.reach_final = r["reach_final"]
        row.win_title = r["win_title"]
        row.as_of = now
    return len(results)


def generate_predictions(
    db: Session,
    model_version: str | None = None,
    n_sims: int = 5000,
    tournament_sims: int = 2000,
) -> dict:
    """Predict every upcoming match with both teams set — all group fixtures plus
    any drawn knockout ties — simulate every group's standings, and run the
    full-tournament (knockout) Monte-Carlo.

    Engine parameters come from ml.models.params.load_params() — the tuned
    model_params.json if present, else the v0.1 constants. The served model
    version follows the loaded params (so v0.2 predictions are tagged v0.2)
    unless an explicit ``model_version`` is passed.
    """
    # Tournament-adjusted strengths (base Elo + conservative delta + capped
    # form) so match predictions and both simulations move together once the
    # learning loop has run. Falls back to base ratings when no state exists.
    from pipeline.learning_loop import effective_elos

    params = load_params()
    active_model_version = model_version or params.version
    strengths = effective_elos(db)

    booster = None
    if params.wdl_blend:
        from pipeline.backtest_data import build_enriched_rows
        from ml.features.training_rows import build_training_rows, training_weight
        from ml.models.wdl_boost import WdlBoost  # deferred: sklearn loads only when the blend ships

        train_rows = build_training_rows(build_enriched_rows(db))
        if train_rows:
            ref = max(r["date"] for r in train_rows)
            weights = [training_weight(r, ref) for r in train_rows]
            booster = WdlBoost().fit(train_rows, sample_weight=weights)

    # Every upcoming match with both teams set: all group fixtures plus any drawn
    # knockout ties. The official bracket links each tie to its match-detail page,
    # which needs a prediction, so KO matches must be predicted once their teams are
    # known (build_payload skips a teamless placeholder defensively anyway).
    matches = (
        db.query(Match)
        .filter(
            Match.status == "scheduled",
            Match.team_home_id.isnot(None),
            Match.team_away_id.isnot(None),
        )
        .all()
    )
    predicted = 0
    for match in matches:
        payload = build_payload(db, match, active_model_version,
                                strengths=strengths, params=params, booster=booster)
        if payload is None:
            continue
        _write_prediction(db, payload, active_model_version)
        # Shadow twin (FR-4.4): odds-anchored when a market total is stored and
        # w_odds > 0, otherwise an exact copy — either way never served.
        write_shadow_prediction(db, match, payload, strengths, params)
        predicted += 1

    groups = db.query(Group).all()
    for group in groups:
        _simulate_standings(db, group, active_model_version, n_sims, strengths=strengths, params=params)

    teams_simulated = _simulate_tournament(db, tournament_sims, strengths=strengths, params=params)

    db.commit()
    return {
        "matches_predicted": predicted,
        "groups_simulated": len(groups),
        "tournament_teams": teams_simulated,
    }
